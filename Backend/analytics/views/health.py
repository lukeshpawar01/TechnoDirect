from django.db.models import Count, Q, Sum
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
    Rsm,
    DataQualityIssue,
    DistributorSettlement,
    Distributor,
    Order,
    Product,
    ProductVariant,
    Region,
    State,
)

from ..derivations import DQ_LABELS
from ..envelope import source_state
from ..filters import add_months, month_end, parse_filters
from ..metrics import mkey, num, pct
from ..styles import options as style_options
from .base import AnalyticsView

# where a run read its data ("via" in SyncRun.details) - shows the dashboard does not depend on files on one PC
VIA_LABEL = {"google_sheet": "Google Sheets API", "dropbox": "Dropbox API", "supabase": "Supabase",
             "file": "a local file (one-off)", "folder": "a local folder"}

CHECKED_IN_REFRESH = {"settlement", "distributor_sync", "blueorigin", "targets_sheet"}
DEFAULT_VIA = {"google_sheets": "Google Sheets API", "supabase": "Supabase (Postgres)", "payu": "PayU API", "channel_konnect": "Channel Konnect API"}

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
        refresh_ok = source_state(REFRESH_SOURCE)[1]
        # sources the last successful "Refresh All" checked and found unchanged (skipped: no run of their own is logged)
        checked_ok = {st.get("source") for st in ((refresh_ok.details or {}).get("steps") or [])
                      if st.get("status") == "skipped"} if refresh_ok is not None else set()
        # the sheet / file sources run inside "Refresh All" but get their own card, with where they were read from
        for s in list(CONNECTORS) + ["settlement", "distributor_sync", "targets_sheet", "blueorigin", "derivations",
                                     REFRESH_SOURCE]:
            last_run, last_success = source_state(s)
            status = evaluate_status(last_run, last_success)
            if last_run is not None and last_run.status == "not_configured":
                status = "not_configured"
            # a sheet / file source is skipped when unchanged (no run is logged): if the last "Refresh All" succeeded
            # after it and its own last run did not fail, it was checked and is current
            if (s in CHECKED_IN_REFRESH and status == "stale" and last_run is not None and last_run.status == "success"
                    and refresh_ok is not None and refresh_ok.finished_at and last_run.finished_at
                    and refresh_ok.finished_at >= last_run.finished_at):
                status = evaluate_status(refresh_ok, refresh_ok)
            # its last own run failed (e.g. no internet) but a later successful refresh read it and found it unchanged:
            # the earlier failure is over - the data is the last successful import, still current
            recovered = (s in checked_ok and last_run is not None and last_run.status == "failed"
                         and refresh_ok.finished_at and last_run.finished_at
                         and refresh_ok.finished_at >= last_run.finished_at and last_success is not None)
            if recovered:
                status = evaluate_status(refresh_ok, refresh_ok)
            sources.append({
                "source": s, "status": status,
                "last_run_at": _iso(last_run.finished_at if last_run else None),
                "last_success_at": _iso(last_success.finished_at if last_success else None),
                # checked by a later successful refresh and found unchanged: when, and the rows of the last real import
                "last_checked_at": _iso(refresh_ok.finished_at) if (
                    s in checked_ok and refresh_ok is not None and refresh_ok.finished_at and last_success is not None
                    and last_success.finished_at and refresh_ok.finished_at > last_success.finished_at) else None,
                "rows_loaded": last_success.rows if last_success else 0,
                "last_error": (last_run.error[:500] if last_run and last_run.error and not recovered else None),
                "rows_last_run": last_run.rows if last_run else 0,
                "via": (VIA_LABEL.get(((last_success.details or {}).get("via") or "").split(":")[0])
                        or DEFAULT_VIA.get(s)) if last_success else None,
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
    """POST {source: supabase|payu|google_sheets|channel_konnect|all}"""

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
        rsms = Rsm.objects.filter(is_active=True)
        if not sc.all:
            rsms = rsms.filter(Q(id__in=asms.values("rsm_id")) | Q(region__in=regions))
        return Response({
            "regions": list(regions.order_by("name").values("id", "name", "code")),
            "states": list(states.order_by("name").values("id", "name", "code", "region_id")),
            "rsms": list(rsms.order_by("name").values("id", "name", "code", "region_id")),
            "asms": list(asms.order_by("name").values("id", "name", "code", "region_id", "rsm_id")),
            # bo_only = offline-only (BlueOrigin sheets); shown on the BlueOrigin page
            "distributors": list(dists.order_by("name").values("id", "name", "code", "state_id", "bo_only")),
            # top-bar Category = Category I of the product catalogue
            "categories": [{"code": c, "name": c.replace("-", " ").title()} for c in Product.objects.exclude(
                category_l1="").values_list("category_l1", flat=True).distinct().order_by("category_l1")],
            "order_statuses": ORDER_STATUSES,
            "payment_statuses": PAYMENT_STATUSES,
            # module filters
            "payment_modes": sorted(m for m in Order.objects.exclude(payment_mode="").values_list(
                "payment_mode", flat=True).distinct()),
            "platforms": sorted(p for p in Order.objects.exclude(platform="").values_list(
                "platform", flat=True).distinct()),
            "category_tree": [
                {"l1": a, "l2": b, "l3": c} for a, b, c in Product.objects.exclude(category_l1="").values_list(
                    "category_l1", "category_l2", "category_l3").distinct().order_by(
                    "category_l1", "category_l2", "category_l3")],
            "sizes": sorted({s for s in ProductVariant.objects.exclude(size="").values_list("size", flat=True)}),
            # base style codes (OR99 covers OR99/B11 etc.) with the latest name and category, for the Style filter
            "styles": style_options(),
            "tiers": ["Platinum", "Gold", "Silver", "Green", "Yellow", "Untiered"],
            # distributor payout batches (finance tracker "Distributor Settlement Date"), newest first
            "payout_dates": [d.isoformat() for d in DistributorSettlement.objects.exclude(settled_on=None).values_list(
                "settled_on", flat=True).distinct().order_by("-settled_on")],
        })


class DataVersionView(APIView):
    """GET -> {version}. Bumped on every data / mapping / target change; open dashboards poll it (every ~15 s)
    and reload as soon as it changes, so a save shows up for every user without waiting for the next refresh."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from ..cache import cache_version

        return Response({"version": cache_version()})


def _ids(qs, field):
    from django.db.models import Q

    return Q(id__in=[i for i in qs.values_list(field, flat=True) if i])
