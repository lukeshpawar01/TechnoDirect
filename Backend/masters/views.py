"""Admin masters: CRUD + xlsx template download + xlsx upload with row-level errors (all audited)."""
import datetime as dt
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import AuditedModelMixin, log_action, snapshot
from accounts.permissions import AUTHENTICATED, HasPerm
from analytics.cache import bump_cache_version
from analytics.export import ExportListMixin
from warehouse.models import Asm, Distributor, Pincode, Region, State, Target

from .models import MetricDefinition, ReconciliationRef
from .serializers import (
    SCOPE_MODELS,
    AsmSerializer,
    MetricSerializer,
    MonthField,
    PincodeSerializer,
    ReconciliationSerializer,
    RegionSerializer,
    StateSerializer,
    TargetSerializer,
)
from .services import remap_retailers_for_pincodes

MAX_UPLOAD_ROWS = 50_000


class RowError(Exception):
    pass


# ----------------------------------------------------------------------------- cell parsing
def _s(v):
    return "" if v is None else str(v).strip()


def _bool(v, default=True):
    s = _s(v).lower()
    if not s:
        return default
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    raise RowError(f"invalid boolean '{v}'")


def _dec(v, field):
    try:
        return Decimal(_s(v).replace(",", ""))
    except InvalidOperation:
        raise RowError(f"{field}: '{v}' is not a number") from None


def _date(v, field, default=None):
    if v in (None, ""):
        return default
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(_s(v), fmt).date()
        except ValueError:
            continue
    raise RowError(f"{field}: '{v}' is not a date (YYYY-MM-DD)")


def _month(v):
    try:
        return MonthField().to_internal_value(v)
    except serializers.ValidationError:
        raise RowError(f"month: '{v}' must be YYYY-MM") from None


def _by_code(model, code, field, required=False):
    code = _s(code)
    if not code:
        if required:
            raise RowError(f"{field} is required")
        return None
    obj = model.objects.filter(Q(code__iexact=code) | Q(name__iexact=code)).first()
    if obj is None:
        raise RowError(f"{field}: unknown code '{code}'")
    return obj


# ----------------------------------------------------------------------------- base viewset
class MasterViewSet(AuditedModelMixin, ExportListMixin, viewsets.ModelViewSet):
    perm = "manage_mappings"
    read_perm = None
    template_columns = []  # [(column, help/example)]
    search_fields = []
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm(self.perm, read=self.read_perm)()]

    filter_backends = [OrderingFilter]
    ordering_fields = "__all__"

    def filter_queryset(self, qs):
        q = self.request.query_params.get("search")
        if q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        return super().filter_queryset(qs)

    @property
    def export_filename(self):
        return self.basename

    def upsert_row(self, row):
        """Return 'created' or 'updated'. Raise RowError for a row-level problem."""
        raise NotImplementedError

    def after_upload(self, results):
        pass

    @action(detail=False, methods=["get"])
    def template(self, request):
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = self.basename[:31]
        ws.append([c for c, _ in self.template_columns])
        ws.append([e for _, e in self.template_columns])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for i, (c, _) in enumerate(self.template_columns, start=1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(14, len(c) + 4)
        help_ws = wb.create_sheet("README")
        help_ws.append(["Row 2 is an example – overwrite or delete it before uploading."])
        help_ws.append(["Codes (region/state/asm/distributor) may also be the exact name."])
        out = io.BytesIO()
        wb.save(out)
        resp = HttpResponse(out.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="{self.basename}_template.xlsx"'
        return resp

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        from openpyxl import load_workbook

        f = request.FILES.get("file")
        if not f:
            raise ValidationError({"file": "multipart field 'file' (xlsx) is required"})
        try:
            wb = load_workbook(f, read_only=True, data_only=True)
        except Exception:  # noqa: BLE001
            raise ValidationError({"file": "not a valid .xlsx file"}) from None
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = [(_s(h).lower()) for h in (next(rows, None) or [])]
        expected = [c for c, _ in self.template_columns]
        missing = [c for c in expected if c not in header and not c.endswith("?")]
        if missing:
            raise ValidationError({"file": f"missing columns: {missing}. Download the template."})
        created = updated = 0
        errors = []
        for idx, values in enumerate(rows, start=2):
            if idx - 1 > MAX_UPLOAD_ROWS:
                errors.append({"row": idx, "message": f"row limit {MAX_UPLOAD_ROWS} exceeded"})
                break
            if values is None or all(v in (None, "") for v in values):
                continue
            row = {header[i]: v for i, v in enumerate(values) if i < len(header) and header[i]}
            try:
                with transaction.atomic():
                    res = self.upsert_row(row)
                if res == "created":
                    created += 1
                else:
                    updated += 1
            except (RowError, DjangoValidationError, ValueError) as exc:
                errors.append({"row": idx, "message": str(exc)})
            except serializers.ValidationError as exc:
                errors.append({"row": idx, "message": _flatten_errors(exc.detail)})
        result = {"created": created, "updated": updated, "errors": errors}
        log_action(request, "upload", None, object_type=f"masters.{self.basename}", object_id=f.name,
                   after={"created": created, "updated": updated, "errors": len(errors)})
        self.after_upload(result)
        bump_cache_version()
        return Response(result)

    def perform_create(self, serializer):
        super().perform_create(serializer)
        bump_cache_version()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        bump_cache_version()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        bump_cache_version()


def _flatten_errors(detail):
    if isinstance(detail, dict):
        return "; ".join(f"{k}: {_flatten_errors(v)}" for k, v in detail.items())
    if isinstance(detail, list):
        return ", ".join(_flatten_errors(x) for x in detail)
    return str(detail)


def _audit_row(request, action_name, obj, before=None):
    log_action(request, action_name, obj, before=before, after=snapshot(obj), reason="xlsx upload")


# ----------------------------------------------------------------------------- targets
class TargetViewSet(MasterViewSet):
    serializer_class = TargetSerializer
    perm = "manage_targets"
    basename = "targets"
    search_fields = ["notes", "metric", "scope_type"]
    template_columns = [
        ("month", "2026-11"), ("scope_type", "overall|region|state|asm|distributor"),
        ("scope_code", "(blank for overall) e.g. KA or DIST001"), ("metric", "sales|orders|new_retailers|active_retailers"),
        ("value", "30000000"), ("effective_from", "2026-11-01"), ("notes", ""),
    ]

    def get_queryset(self):
        qs = Target.objects.all()
        p = self.request.query_params
        if p.get("month"):
            qs = qs.filter(month=_month(p["month"]))
        if p.get("scope_type"):
            qs = qs.filter(scope_type=p["scope_type"])
        if p.get("metric"):
            qs = qs.filter(metric=p["metric"])
        return qs.order_by("-month", "scope_type", "scope_id", "metric", "-effective_from")

    def perform_create(self, serializer):
        obj = serializer.save(updated_by=self.request.user.email)
        log_action(self.request, "create", obj, after=snapshot(obj))
        bump_cache_version()

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        obj = serializer.save(version=serializer.instance.version + 1, updated_by=self.request.user.email)
        log_action(self.request, "update", obj, before=before, after=snapshot(obj))
        bump_cache_version()

    def upsert_row(self, row):
        month = _month(row.get("month"))
        st = _s(row.get("scope_type")).lower() or "overall"
        if st not in ("overall", "region", "state", "asm", "distributor"):
            raise RowError(f"scope_type '{st}' invalid")
        metric = _s(row.get("metric")).lower() or "sales"
        if metric not in dict(Target.METRICS):
            raise RowError(f"metric '{metric}' invalid")
        value = _dec(row.get("value"), "value")
        if value < 0:
            raise RowError("value must be >= 0")
        scope_id = None
        if st != "overall":
            raw_id = _s(row.get("scope_id"))
            if raw_id.isdigit():
                scope_id = int(raw_id)
                if not SCOPE_MODELS[st].objects.filter(pk=scope_id).exists():
                    raise RowError(f"unknown {st} id {scope_id}")
            else:
                scope_id = _by_code(SCOPE_MODELS[st], row.get("scope_code"), "scope_code", required=True).id
        eff = _date(row.get("effective_from"), "effective_from", default=dt.date.today())
        obj = Target.objects.filter(month=month, scope_type=st, scope_id=scope_id, metric=metric,
                                    effective_from=eff).first()
        email = self.request.user.email
        if obj:
            before = snapshot(obj)
            obj.value, obj.notes = value, _s(row.get("notes"))[:255]
            obj.version += 1
            obj.updated_by = email
            obj.save()
            _audit_row(self.request, "update", obj, before)
            return "updated"
        obj = Target.objects.create(month=month, scope_type=st, scope_id=scope_id, metric=metric, value=value,
                                    effective_from=eff, notes=_s(row.get("notes"))[:255], updated_by=email)
        _audit_row(self.request, "create", obj)
        return "created"


# ----------------------------------------------------------------------------- geography
class RegionViewSet(MasterViewSet):
    serializer_class = RegionSerializer
    basename = "regions"
    search_fields = ["code", "name"]
    template_columns = [("code", "SOUTH1"), ("name", "South 1")]

    def get_queryset(self):
        return Region.objects.order_by("name")

    def upsert_row(self, row):
        code = _s(row.get("code"))
        if not code:
            raise RowError("code is required")
        obj, created = Region.objects.update_or_create(code=code, defaults={"name": _s(row.get("name")) or code})
        _audit_row(self.request, "create" if created else "update", obj)
        return "created" if created else "updated"


class StateViewSet(MasterViewSet):
    serializer_class = StateSerializer
    basename = "states"
    search_fields = ["code", "name"]
    template_columns = [("code", "KA"), ("name", "Karnataka"), ("region_code", "SOUTH1")]

    def get_queryset(self):
        return State.objects.select_related("region").order_by("name")

    def upsert_row(self, row):
        code = _s(row.get("code"))
        if not code:
            raise RowError("code is required")
        region = _by_code(Region, row.get("region_code"), "region_code")
        obj, created = State.objects.update_or_create(code=code, defaults={
            "name": _s(row.get("name")) or code, "region": region})
        _audit_row(self.request, "create" if created else "update", obj)
        return "created" if created else "updated"


class AsmViewSet(MasterViewSet):
    serializer_class = AsmSerializer
    basename = "asms"
    search_fields = ["code", "name", "email"]
    template_columns = [("code", "ASM01"), ("name", "Ravi Kumar"), ("email", "ravi@example.com"),
                        ("phone", "9800000000"), ("region_code", "SOUTH1"), ("is_active", "TRUE")]

    def get_queryset(self):
        return Asm.objects.select_related("region").order_by("name")

    def upsert_row(self, row):
        code = _s(row.get("code"))
        if not code:
            raise RowError("code is required")
        obj, created = Asm.objects.update_or_create(code=code, defaults={
            "name": _s(row.get("name")) or code, "email": _s(row.get("email")), "phone": _s(row.get("phone"))[:20],
            "region": _by_code(Region, row.get("region_code"), "region_code"),
            "is_active": _bool(row.get("is_active"))})
        _audit_row(self.request, "create" if created else "update", obj)
        return "created" if created else "updated"


class PincodeViewSet(MasterViewSet):
    serializer_class = PincodeSerializer
    basename = "pincodes"
    search_fields = ["pincode", "district", "city"]
    template_columns = [
        ("pincode", "560001"), ("district", "Bengaluru Urban"), ("city", "Bengaluru"), ("state_code", "KA"),
        ("asm_code", "ASM01"), ("distributor_p1_code", "HEERA"), ("distributor_p2_code", ""),
        ("is_serviceable", "TRUE"),
    ]

    def get_queryset(self):
        qs = Pincode.objects.select_related("state", "asm", "distributor_p1", "distributor_p2").order_by("pincode")
        p = self.request.query_params
        if p.get("state"):
            qs = qs.filter(state_id__in=p["state"].split(","))
        if p.get("unmapped") in ("1", "true"):
            qs = qs.filter(Q(asm__isnull=True) | Q(distributor_p1__isnull=True))
        return qs

    def perform_create(self, serializer):
        super().perform_create(serializer)
        remap_retailers_for_pincodes([serializer.instance.pincode])

    def perform_update(self, serializer):
        super().perform_update(serializer)
        remap_retailers_for_pincodes([serializer.instance.pincode])

    def upsert_row(self, row):
        pin = _s(row.get("pincode")).split(".")[0]
        if len(pin) != 6 or not pin.isdigit() or pin[0] == "0":
            raise RowError(f"pincode '{pin}' must be 6 digits")
        defaults = {
            "district": _s(row.get("district"))[:100], "city": _s(row.get("city"))[:100],
            "state": _by_code(State, row.get("state_code"), "state_code", required=True),
            "asm": _by_code(Asm, row.get("asm_code"), "asm_code"),
            "distributor_p1": _by_code(Distributor, row.get("distributor_p1_code"), "distributor_p1_code"),
            "distributor_p2": _by_code(Distributor, row.get("distributor_p2_code"), "distributor_p2_code"),
            "is_serviceable": _bool(row.get("is_serviceable")),
        }
        obj, created = Pincode.objects.update_or_create(pincode=pin, defaults=defaults)
        self._uploaded = getattr(self, "_uploaded", []) + [pin]
        _audit_row(self.request, "create" if created else "update", obj)
        return "created" if created else "updated"

    def after_upload(self, results):
        remap_retailers_for_pincodes(getattr(self, "_uploaded", []))


class ReconciliationViewSet(MasterViewSet):
    serializer_class = ReconciliationSerializer
    perm = "manage_metrics"
    read_perm = "view_data_health"
    basename = "reconciliation"
    search_fields = ["metric", "notes"]
    template_columns = [("metric", "sales|orders|active_retailers|new_retailers|units"), ("month", "2026-10"),
                        ("mis_value", "29500000"), ("tolerance_pct", "1"), ("notes", "")]

    def get_queryset(self):
        return ReconciliationRef.objects.order_by("-month", "metric")

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user.email)
        log_action(self.request, "create", serializer.instance, after=snapshot(serializer.instance))

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        serializer.save(updated_by=self.request.user.email)
        log_action(self.request, "update", serializer.instance, before=before, after=snapshot(serializer.instance))

    def upsert_row(self, row):
        metric = _s(row.get("metric")).lower()
        if metric not in dict(ReconciliationRef.METRICS):
            raise RowError(f"metric '{metric}' invalid")
        tol = _s(row.get("tolerance_pct"))
        obj, created = ReconciliationRef.objects.update_or_create(
            metric=metric, month=_month(row.get("month") or row.get("period")), defaults={
                "mis_value": _dec(row.get("mis_value"), "mis_value"),
                "tolerance_pct": _dec(tol, "tolerance_pct") if tol else Decimal("1"),
                "notes": _s(row.get("notes"))[:255], "updated_by": self.request.user.email})
        _audit_row(self.request, "create" if created else "update", obj)
        return "created" if created else "updated"


# ----------------------------------------------------------------------------- metric dictionary
class MetricDictionaryView(APIView):
    """GET list (any logged-in user). PATCH a single {code,...} or a list of them (manage_metrics)."""

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("manage_metrics", read=AUTHENTICATED)()]

    def get(self, request, code=None):
        if code:
            obj = MetricDefinition.objects.filter(code=code).first()
            if not obj:
                return Response({"detail": "Not found."}, status=404)
            return Response(MetricSerializer(obj).data)
        return Response(MetricSerializer(MetricDefinition.objects.order_by("code"), many=True).data)

    def patch(self, request, code=None):
        items = request.data if isinstance(request.data, list) else [dict(request.data, **({"code": code} if code else {}))]
        out = []
        with transaction.atomic():
            for item in items:
                c = item.get("code")
                obj = MetricDefinition.objects.filter(code=c).first()
                if obj is None:
                    obj = MetricDefinition(code=c)
                    before = None
                else:
                    before = snapshot(obj)
                s = MetricSerializer(obj, data=item, partial=obj.pk is not None)
                s.is_valid(raise_exception=True)
                s.save()
                log_action(request, "update" if before else "create", s.instance, before=before,
                           after=snapshot(s.instance))
                out.append(s.data)
        return Response(out if isinstance(request.data, list) else out[0])
