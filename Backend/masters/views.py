"""Admin masters: CRUD + xlsx template download + xlsx upload with row-level errors (all audited)."""
import datetime as dt
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils.timezone import localdate  # India date (TIME_ZONE), not the server clock
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
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
        eff = _date(row.get("effective_from"), "effective_from", default=localdate())
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


# ----------------------------------------------------------------------------- ASM tracker
class AsmTrackerView(APIView):
    """GET  ?month=YYYY-MM[&download=xlsx]  -> tracker rows + ASM summary (xlsx needs export_data)
    POST {month, rows:[{distributor_id, region, asm, target}], asm_targets:[{asm, target}]} -> save
         (manage_targets + manage_mappings). asm_targets only applies to ASMs with no distributor targets."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), HasPerm("view_territory")()]
        return [IsAuthenticated(), HasPerm("manage_targets")(), HasPerm("manage_mappings")()]

    def get(self, request):
        from .asm_tracker import parse_month, to_xlsx, tracker

        try:
            month = parse_month(request.query_params.get("month"))
        except ValueError as e:
            raise ValidationError({"month": str(e)}) from None
        data = tracker(month, request.user)
        if request.query_params.get("download") == "xlsx":
            if not request.user.has_code("export_data"):
                return Response({"detail": "Your role cannot export data."}, status=403)
            log_action(request, "export", None, object_type="asm_tracker", object_id=data["month"])
            resp = HttpResponse(to_xlsx(data),
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            resp["Content-Disposition"] = f'attachment; filename="ASM_tracker_{data["month"]}.xlsx"'
            return resp
        return Response(data)

    def post(self, request):
        from .asm_tracker import apply_rows, parse_month

        try:
            month = parse_month(request.data.get("month"))
        except ValueError as e:
            raise ValidationError({"month": str(e)}) from None
        names = dict(Distributor.objects.values_list("id", "name"))
        rows = []
        for i, r in enumerate(request.data.get("rows") or [], start=1):
            did = r.get("distributor_id")
            if did not in names:
                raise ValidationError({"rows": f"row {i}: unknown distributor id {did}"})
            target = r.get("target")
            if target not in (None, ""):
                try:
                    if Decimal(str(target)) < 0:
                        raise ValidationError({"rows": f"row {i}: target must be ≥ 0"})
                except InvalidOperation:
                    raise ValidationError({"rows": f"row {i}: target must be a number"}) from None
            row = {"Distributor": names[did], "Region": str(r.get("region") or "").strip(),
                   "ASM": str(r.get("asm") or "").strip()[:120],
                   "Total Target": "" if target in (None, "") else str(target)}
            # what the editor showed when it loaded: an untouched cell must not overwrite a newer mapping
            if "asm_orig" in r:
                row["ASM Original"] = str(r.get("asm_orig") or "").strip()
            if "region_orig" in r:
                row["Region Original"] = str(r.get("region_orig") or "").strip()
            rows.append(row)
        if not rows:
            raise ValidationError({"rows": "nothing to save"})
        asm_targets = []
        for i, a in enumerate(request.data.get("asm_targets") or [], start=1):
            v = a.get("target")
            if v not in (None, ""):
                try:
                    if Decimal(str(v)) < 0:
                        raise ValidationError({"asm_targets": f"row {i}: target must be >= 0"})
                except InvalidOperation:
                    raise ValidationError({"asm_targets": f"row {i}: target must be a number"}) from None
            asm_targets.append({"asm": str(a.get("asm") or "").strip(), "target": v})
        from .target_sheet import SHEET_MSG, sheet_managed

        if sheet_managed(month):
            raise ValidationError({"month": SHEET_MSG.format(m=month.strftime("%B %Y"))})
        result = apply_rows(rows, month, f"edited on screen by {request.user.email}", asm_targets=asm_targets)
        log_action(request, "update", None, object_type="asm_tracker", object_id=month.isoformat()[:7],
                   after={"rows": len(rows), "targets": result.get("targets")})
        return Response({"saved": len(rows), "result": result})


class ExecutivePerformanceView(APIView):
    """GET ?month=YYYY-MM -> executives' targets (incentive sheet) vs their distributors' sales."""

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("view_territory")()]

    def get(self, request):
        from .asm_tracker import parse_month
        from .target_sheet import executive_performance

        try:
            month = parse_month(request.query_params.get("month"))
        except ValueError as e:
            raise ValidationError({"month": str(e)}) from None
        return Response(executive_performance(month, request.user))


class AsmTrackerUploadView(APIView):
    """POST multipart {file: .xlsx|.csv in the tracker layout, month: YYYY-MM}"""

    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("manage_targets")(), HasPerm("manage_mappings")()]

    def post(self, request):
        from .asm_tracker import apply_rows, parse_month, rows_from_file

        f = request.FILES.get("file")
        if not f:
            raise ValidationError({"file": "Choose the tracker file (.xlsx or .csv)."})
        try:
            month = parse_month(request.data.get("month"))
            rows, total = rows_from_file(f)
        except ValueError as e:
            raise ValidationError({"file": str(e)}) from None
        from .target_sheet import SHEET_MSG, sheet_managed

        if sheet_managed(month):
            raise ValidationError({"file": SHEET_MSG.format(m=month.strftime("%B %Y"))})
        result = apply_rows(rows, month, f"upload {f.name}", total)
        log_action(request, "upload", None, object_type="asm_tracker", object_id=f.name,
                   after={"month": month.isoformat()[:7], "rows": len(rows), "targets": result.get("targets")})
        return Response({"saved": len(rows), "result": result})


class AsmTrackerCreateView(APIView):
    """POST /masters/asm-tracker/asm/          {name, full_name, region, rsm_id, joined_on}  -> new ASM
       POST /masters/asm-tracker/distributor/  {name, state_id, city, asm}                    -> new distributor
    From the Edit ASM & targets window (perm manage_mappings)."""

    kind = None

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("manage_mappings")()]

    def post(self, request):
        from analytics.cache import bump_cache_version

        from .asm_tracker import create_asm, create_distributor

        try:
            obj = create_asm(request.data) if self.kind == "asm" else create_distributor(request.data)
        except ValueError as e:
            raise ValidationError({"detail": str(e)}) from None
        log_action(request, "create", obj)
        bump_cache_version()
        return Response({"id": obj.id, "name": obj.name}, status=201)


# ----------------------------------------------------------------------------- P&L (Business Head + master admin)
def pnl_allowed(user, code):
    """The master admin, or a user of the Business Head role holding the code. Checked on every P&L request, so the
    P&L stays restricted even if the permission were put on another role."""
    from accounts.models import PNL_ROLE

    if not user or not user.is_authenticated:
        return False
    if user.is_master_admin:
        return True
    return bool(user.role_id and user.role.name == PNL_ROLE and user.has_code(code))


class PnlPermission(permissions.BasePermission):
    message = "The P&L is available to the Business Head and the admin only."

    def has_permission(self, request, view):
        code = "view_pnl" if request.method in permissions.SAFE_METHODS else "manage_pnl"
        return pnl_allowed(request.user, code)


def _pnl_amount(value, field, pct=False):
    from decimal import Decimal, InvalidOperation

    if value in (None, ""):
        if pct:
            raise ValidationError({field: "required"})
        return None
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise ValidationError({field: "must be a number"}) from None
    if d < 0 or (pct and d > 100):
        raise ValidationError({field: "must be between 0 and 100" if pct else "cannot be negative"})
    return d


class PnlView(APIView):
    """GET /api/masters/pnl/ - the P&L statement, quarter on quarter, with checks against the data.
    ?export=csv|xlsx downloads the statement laid out like the Excel sheet."""

    permission_classes = [IsAuthenticated, PnlPermission]

    def get(self, request):
        from analytics.export import rows_to_response

        from .pnl import export_rows, statement

        data = statement()
        fmt = request.query_params.get("export")
        if fmt:
            log_action(request, "export", None, object_type="pnl", object_id=fmt)
            return rows_to_response(export_rows(data), "TD_PnL_QoQ", fmt)
        data["can_edit"] = pnl_allowed(request.user, "manage_pnl")
        return Response(data)


class PnlQuarterView(APIView):
    """POST /api/masters/pnl/quarters/            add the next quarter (costs and % carried forward)
       PATCH /api/masters/pnl/quarters/<start>/   change a quarter's inputs
       DELETE /api/masters/pnl/quarters/<start>/  remove the latest quarter (undo an add)"""

    permission_classes = [IsAuthenticated, PnlPermission]
    PCTS = {"cogs_pct", "pg_pct", "loyalty_pct"}
    AMOUNTS = {"gross_revenue", "returns", "tech_platform_cost", "manpower_operating_cost", "misc_expense"}

    def _get(self, start):
        from .models import PnlQuarter

        try:
            return PnlQuarter.objects.get(quarter_start=dt.date.fromisoformat(start))
        except (ValueError, PnlQuarter.DoesNotExist):
            raise NotFound("No such P&L quarter") from None

    def post(self, request):
        from .models import PnlQuarter
        from .pnl import CARRY_FORWARD, is_quarter_start, next_quarter, quarter_label

        latest = PnlQuarter.objects.order_by("-quarter_start").first()
        raw = request.data.get("quarter_start")
        try:
            start = dt.date.fromisoformat(raw) if raw else (next_quarter(latest.quarter_start) if latest else None)
        except ValueError:
            raise ValidationError({"quarter_start": "use YYYY-MM-DD"}) from None
        if start is None or not is_quarter_start(start):
            raise ValidationError({"quarter_start": "must be the first day of a quarter (1 Apr / Jul / Oct / Jan)"})
        if start > localdate():
            raise ValidationError({"quarter_start": f"{quarter_label(start)} has not started yet"})
        if PnlQuarter.objects.filter(quarter_start=start).exists():
            raise ValidationError({"quarter_start": f"{quarter_label(start)} already exists"})
        carry = {f: getattr(latest, f) for f in CARRY_FORWARD} if latest else {}
        obj = PnlQuarter.objects.create(quarter_start=start, updated_by=request.user.email,
                                        notes=f"Costs and % carried forward from {quarter_label(latest.quarter_start)}"
                                        if latest else "", **carry)
        log_action(request, "create", obj, after=snapshot(obj))
        return Response({"start": start.isoformat(), "label": quarter_label(start)}, status=201)

    def patch(self, request, start):
        obj = self._get(start)
        before = snapshot(obj)
        changed = []
        for field in self.AMOUNTS | self.PCTS:
            if field in request.data:
                setattr(obj, field, _pnl_amount(request.data[field], field, pct=field in self.PCTS))
                changed.append(field)
        if "notes" in request.data:
            obj.notes = str(request.data.get("notes") or "")[:2000]
            changed.append("notes")
        if not changed:
            raise ValidationError({"detail": "nothing to change"})
        obj.updated_by = request.user.email
        obj.save()
        log_action(request, "update", obj, before=before, after=snapshot(obj))
        return Response({"updated": sorted(changed)})

    def delete(self, request, start):
        from .models import PnlQuarter

        obj = self._get(start)
        if PnlQuarter.objects.filter(quarter_start__gt=obj.quarter_start).exists():
            raise ValidationError({"detail": "Only the latest quarter can be removed"})
        log_action(request, "delete", obj, before=snapshot(obj))
        obj.delete()
        return Response(status=204)


class ManualMappingsView(APIView):
    """GET -> mappings given by hand (chat), active first. POST {id, undo} -> remove one (undo = reverse its effect)."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), HasPerm("manage_targets")()]
        return [IsAuthenticated(), HasPerm("view_data_health")()]

    def get(self, request):
        from . import manual_mappings as mm
        from .models import ManualMapping

        rows = [mm.as_dict(e) for e in ManualMapping.objects.select_related("distributor", "asm")]
        rows.sort(key=lambda r: (r["status"] != "active", r["kind"], r["distributor"] or ""))
        return Response({"rows": rows, "active": sum(1 for r in rows if r["status"] == "active")})

    def post(self, request):
        from . import manual_mappings as mm
        from .models import ManualMapping

        e = ManualMapping.objects.filter(id=request.data.get("id"), status="active").first()
        if e is None:
            raise NotFound("No active manual mapping with that id")
        before = mm.as_dict(e)
        mm.remove(e, undo=bool(request.data.get("undo", True)), reason=f"removed by {request.user.email}")
        log_action(request, "delete", e, before=before, after=mm.as_dict(e))
        return Response(mm.as_dict(e))


class IncentiveTrackerView(APIView):
    """GET ?month=YYYY-MM -> ASM & executive incentive tracker (masters/incentives.py)."""

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("view_territory")()]

    def get(self, request):
        from .asm_tracker import parse_month
        from .incentives import tracker

        try:
            month = parse_month(request.query_params.get("month"))
        except ValueError as e:
            raise ValidationError({"month": str(e)}) from None
        return Response(tracker(month, request.user))


class IncentiveRetailersView(APIView):
    """GET ?month=YYYY-MM&kpi=new|gps|kyc&tier=Gold,None&distributor=<ids>&asm=<id> -> the retailers behind the counts."""

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("view_territory")()]

    def get(self, request):
        from .asm_tracker import parse_month
        from .incentives import retailer_list

        p = request.query_params
        try:
            month = parse_month(p.get("month"))
        except ValueError as e:
            raise ValidationError({"month": str(e)}) from None
        tiers = [t.strip().title() if t.strip().lower() != "none" else "None" for t in (p.get("tier") or "").split(",") if t.strip()]
        dist = [int(x) for x in (p.get("distributor") or "").split(",") if x.strip().isdigit()]
        asm = p.get("asm")
        rows = retailer_list(month, request.user, kpi=p.get("kpi") or None, tiers=tiers or None,
                             distributor_ids=dist or None, asm_id=int(asm) if asm and asm.isdigit() else None,
                             can_see_phone=request.user.has_code("view_pii"))
        return Response({"month": month.isoformat()[:7], "rows": rows})


class IncentiveSheetEditView(APIView):
    """GET ?month=YYYY-MM -> the month's incentive sheet rows to edit (a copy of the last month when it has none).
    PUT {month, rows: [{distributor_id, role, person, td_target, new_target, gps_target, kyc_target}]} -> replaces the
    month, sheet order kept. Perm manage_targets."""

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("manage_targets")()]

    def _month(self, value):
        from .asm_tracker import parse_month

        try:
            return parse_month(value)
        except ValueError as e:
            raise ValidationError({"month": str(e)}) from None

    def get(self, request):
        from .target_sheet import editor

        return Response(editor(self._month(request.query_params.get("month"))))

    def put(self, request):
        from .target_sheet import TargetSheetError, save_month

        month = self._month(request.data.get("month"))
        rows = request.data.get("rows")
        if not isinstance(rows, list):
            raise ValidationError({"rows": "rows must be a list"})
        try:
            report = save_month(month, rows, request.user.email)
        except TargetSheetError as e:
            raise ValidationError({"rows": str(e)}) from None
        log_action(request, "update", None, object_type="incentive_sheet", object_id=month.isoformat()[:7],
                   after={"rows": len(rows), "report": report.get(month.isoformat()[:7])})
        return Response({"saved": len(rows), "report": report})


class IncentiveAchievedView(APIView):
    """POST {id, kpi: td|new|gps|kyc, value: number | null} -> type in (or clear) a row's achieved value; the payout
    factor, payout % and payment follow it. Perm manage_targets."""

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("manage_targets")()]

    def post(self, request):
        from .incentives import set_achieved

        try:
            s, before, after = set_achieved(int(request.data.get("id") or 0), request.data.get("kpi"),
                                            request.data.get("value"), request.user.email)
        except LookupError:
            raise NotFound("Row not found") from None
        except ValueError as e:
            raise ValidationError({"value": str(e)}) from None
        log_action(request, "update", None, object_type="incentive_achieved", object_id=str(s.id),
                   before={request.data.get("kpi"): str(before) if before is not None else None},
                   after={request.data.get("kpi"): str(after) if after is not None else None,
                          "person": s.person, "distributor": s.distributor.name, "month": s.month.isoformat()[:7]})
        return Response({"id": s.id, "kpi": request.data.get("kpi"), "value": float(after) if after is not None else None})


class IncentiveSheetView(APIView):
    """GET ?month=YYYY-MM -> the incentive sheet row for row, achievement computed (masters/incentives.sheet_table)."""

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("view_territory")()]

    def get(self, request):
        from .asm_tracker import parse_month
        from .incentives import sheet_table

        try:
            month = parse_month(request.query_params.get("month"))
        except ValueError as e:
            raise ValidationError({"month": str(e)}) from None
        return Response(sheet_table(month, request.user))


# ----------------------------------------------------------------------------- Monthly Business Review (MBR)
def _mbr_month(raw):
    from analytics.views.mbr import parse_month

    return parse_month(raw, localdate())


def _mbr_changed():
    bump_cache_version()  # the scorecard's goal maths reads the review


class MbrView(APIView):
    """GET /api/masters/mbr/?month=YYYY-MM   the month's commentary, goal and lines (pages 2-4)
       PUT /api/masters/mbr/?month=YYYY-MM   save commentary / goal {went_well, needs_attention, goal_monthly_sales, goal_by}"""

    permission_classes = [IsAuthenticated, HasPerm("manage_mbr", read="view_mbr")]

    def get(self, request):
        from .mbr import month_payload

        m = _mbr_month(request.query_params.get("month"))
        return Response(month_payload(m, localdate(), request.user.has_code("manage_mbr")))

    def put(self, request):
        from .mbr import month_payload, save_review

        m = _mbr_month(request.query_params.get("month") or request.data.get("month"))
        with transaction.atomic():
            r = save_review(m, request.data, request.user.email)
            log_action(request, "update", r, after=snapshot(r))
        _mbr_changed()
        return Response(month_payload(m, localdate(), True))


class MbrItemView(APIView):
    """POST /api/masters/mbr/items/?month=YYYY-MM  add a line;  PATCH / DELETE /api/masters/mbr/items/<id>/"""

    permission_classes = [IsAuthenticated, HasPerm("manage_mbr")]

    def _get(self, pk):
        from .models import MbrItem

        try:
            return MbrItem.objects.get(pk=pk)
        except MbrItem.DoesNotExist:
            raise NotFound("No such MBR line") from None

    def post(self, request):
        from .mbr import apply_item, item_json
        from .models import MbrItem

        m = _mbr_month(request.query_params.get("month") or request.data.get("month"))
        item = apply_item(MbrItem(month=m, created_by=request.user.email), request.data, partial=False)
        item.updated_by = request.user.email
        item.save()
        log_action(request, "create", item, after=snapshot(item))
        return Response(item_json(item, localdate()), status=201)

    def patch(self, request, pk):
        from .mbr import apply_item, item_json

        item = self._get(pk)
        before = snapshot(item)
        apply_item(item, request.data, partial=True)
        item.updated_by = request.user.email
        item.save()
        log_action(request, "update", item, before=before, after=snapshot(item))
        return Response(item_json(item, localdate()))

    def delete(self, request, pk):
        item = self._get(pk)
        log_action(request, "delete", item, before=snapshot(item))
        item.delete()
        return Response(status=204)


class MbrCarryForwardView(APIView):
    """POST /api/masters/mbr/carry-forward/?month=YYYY-MM  copy last month's open growth and tech lines."""

    permission_classes = [IsAuthenticated, HasPerm("manage_mbr")]

    def post(self, request):
        from .mbr import carry_forward

        m = _mbr_month(request.query_params.get("month") or request.data.get("month"))
        with transaction.atomic():
            n = carry_forward(m, request.user.email)
        log_action(request, "create", None, object_type="mbr_carry_forward", object_id=m.isoformat()[:7])
        _mbr_changed()
        return Response({"copied": n})
