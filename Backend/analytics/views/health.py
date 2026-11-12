from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import log_action
from accounts.permissions import HasPerm
from accounts.scope import ASM_DIMS, DISTRIBUTOR_DIMS, REGION_DIMS, STATE_DIMS
from ingestion.connectors import CONNECTORS
from ingestion.models import SyncRun
from ingestion.schedule import REFRESH_SOURCE, evaluate_status, next_scheduled
from masters.models import ReconciliationRef
from warehouse.models import (
    ORDER_STATUSES,
    PAYMENT_STATUSES,
    Asm,
    Category,
    DataQualityIssue,
    Distributor,
    Region,
    State,
)

from ..derivations import DQ_LABELS
from ..envelope import source_state
from ..filters import add_months, month_end, parse_filters
from ..metrics import mkey, num, pct
from .base import AnalyticsView

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _iso(v):
    return timezone.localtime(v).isoformat(timespec="seconds") if v else None


def recon_dashboard_value(metric, month):
    from analytics.filters import system_filters

    f = system_filters()
    qs = f.orders(start=month, end=month_end(month))
    if metric == "sales":
        return float(qs.aggregate(s=Sum("gross_value"))["s"] or 0)
    if metric == "orders":
        return qs.values("split_group").distinct().count()
    if metric == "active_retailers":
        return qs.values("retailer_id").distinct().count()
    if metric == "new_retailers":
        return qs.filter(retailer__first_order_date__gte=month,
                         retailer__first_order_date__lte=month_end(month)).values("retailer_id").distinct().count()
    if metric == "units":
        return float(qs.aggregate(u=Sum("units"))["u"] or 0)
    return None


class DataHealthView(AnalyticsView):
    permission_code = "view_data_health"
    sources = list(CONNECTORS)

    def compute(self, f, request, **kw):
        nxt = _iso(next_scheduled())
        sources = []
        for s in list(CONNECTORS) + ["derivations", REFRESH_SOURCE]:
            last_run, last_success = source_state(s)
            status = evaluate_status(last_run, last_success)
            if last_run is not None and last_run.status == "not_configured":
                status = "not_configured"
            sources.append({
                "source": s, "status": status,
                "last_run_at": _iso(last_run.finished_at if last_run else None),
                "last_success_at": _iso(last_success.finished_at if last_success else None),
                "last_error": (last_run.error[:500] if last_run and last_run.error else None),
                "rows_last_run": last_run.rows if last_run else 0,
                "next_run_at": nxt,
            })
        issues = []
        for code, label, sev, n in (DataQualityIssue.objects.filter(resolved_at__isnull=True)
                                    .values_list("code", "label", "severity").annotate(n=Count("id"))):
            issues.append({"code": code, "label": label, "count": n, "severity": sev})
        present = {i["code"] for i in issues}
        for code, (label, sev) in DQ_LABELS.items():
            if code not in present:
                issues.append({"code": code, "label": label, "count": 0, "severity": sev})
        issues.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 3), -i["count"]))

        def sample(code, n=50):
            return [dict(i["details"], id=i["object_id"]) for i in DataQualityIssue.objects.filter(
                code=code, resolved_at__isnull=True).values("object_id", "details")[:n]]

        payment_mismatches = {
            "payu_success_no_order": {"count": DataQualityIssue.objects.filter(
                code="payu_success_no_order", resolved_at__isnull=True).count(),
                "rows": sample("payu_success_no_order")},
            "paid_order_no_payu": {"count": DataQualityIssue.objects.filter(
                code="paid_order_no_payu", resolved_at__isnull=True).count(),
                "rows": sample("paid_order_no_payu")},
        }
        recon = []
        cutoff = add_months(f.today.replace(day=1), -12)
        for r in ReconciliationRef.objects.filter(month__gte=cutoff).order_by("-month", "metric"):
            dv = recon_dashboard_value(r.metric, r.month)
            recon.append({"metric": r.metric, "period": mkey(r.month), "dashboard_value": num(dv),
                          "mis_value": num(r.mis_value),
                          "diff_pct": pct((dv or 0) - float(r.mis_value), float(r.mis_value)),
                          "tolerance_pct": float(r.tolerance_pct)})
        issue_filter = request.query_params.get("issue")
        out = {"sources": sources, "issues": issues, "reconciliation": recon,
               "payment_mismatches": payment_mismatches}
        if issue_filter:
            out["issue_rows"] = sample(issue_filter, 500)
        return out


class SyncTriggerView(APIView):
    """POST {source: medusa|payu|google_sheets|channel_konnect|all}"""

    permission_classes = [IsAuthenticated, HasPerm("trigger_sync")]

    def post(self, request):
        from django.conf import settings

        from ingestion.tasks import sync_source

        source = (request.data.get("source") or "all").strip()
        if source != "all" and source not in CONNECTORS:
            raise ValidationError({"source": f"must be one of {sorted(CONNECTORS) + ['all']}"})
        log_action(request, "trigger_sync", None, object_type="sync", object_id=source,
                   after={"source": source})
        trig = f"manual:{request.user.email}"
        if settings.CELERY_TASK_ALWAYS_EAGER:
            result = sync_source.apply(args=[source, trig]).get()
            return Response({"queued": False, "source": source, "result": result})
        task = sync_source.delay(source, trig)
        return Response({"queued": True, "source": source, "task_id": task.id}, status=202)


class FilterOptionsView(APIView):
    def get(self, request):
        f = parse_filters(request)
        sc = f.scope
        regions = Region.objects.all()
        states = State.objects.all()
        asms = Asm.objects.all()
        dists = Distributor.objects.filter(is_active=True)
        if not sc.all:
            dists = dists.filter(sc.q(DISTRIBUTOR_DIMS))
            states = states.filter(sc.q(STATE_DIMS) | _ids(dists, "state_id"))
            regions = regions.filter(sc.q(REGION_DIMS) | _ids(dists, "region_id") | _ids(states, "region_id"))
            asms = asms.filter(sc.q(ASM_DIMS) | _ids(dists, "asm_id"))
        return Response({
            "regions": list(regions.order_by("name").values("id", "name", "code")),
            "states": list(states.order_by("name").values("id", "name", "code", "region_id")),
            "asms": list(asms.order_by("name").values("id", "name", "code", "region_id")),
            "distributors": list(dists.order_by("name").values("id", "name", "code", "state_id")),
            "categories": list(Category.objects.filter(level=1).order_by("name").values("code", "name")),
            "order_statuses": ORDER_STATUSES,
            "payment_statuses": PAYMENT_STATUSES,
        })


def _ids(qs, field):
    from django.db.models import Q

    return Q(id__in=[i for i in qs.values_list(field, flat=True) if i])
