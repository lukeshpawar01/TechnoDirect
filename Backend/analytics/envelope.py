"""Response envelope {data, meta} and freshness reporting."""
from django.utils import timezone
from rest_framework.response import Response

from ingestion.models import SyncRun
from ingestion.schedule import REFRESH_SOURCE, evaluate_status, next_scheduled

SALES_BASIS = "Gross order value of paid orders (PayU-verified), before returns"


def _iso(v):
    return timezone.localtime(v).isoformat(timespec="seconds") if v else None


def source_state(source):
    last_run = SyncRun.objects.filter(source=source).exclude(status__in=["running", "skipped"]).first()
    last_success = SyncRun.objects.filter(source=source, status="success").first()
    return last_run, last_success


def freshness(sources):
    out = []
    for s in sources:
        last_run, last_success = source_state(s)
        item = {
            "source": s,
            "last_success_at": _iso(last_success.finished_at if last_success else None),
            "status": evaluate_status(last_run, last_success),
        }
        if last_run is not None and last_run.status == "not_configured":
            item["detail"] = "not_configured"
        out.append(item)
    return out


def refresh_meta():
    last = SyncRun.objects.filter(source=REFRESH_SOURCE, status="success").first()
    return {
        "last_refresh_at": _iso(last.finished_at if last else None),
        "next_refresh_at": _iso(next_scheduled()),
    }


def build_meta(filters, sources, computed_at=None):
    meta = {
        "sales_basis": SALES_BASIS,
        "as_of": computed_at or _iso(timezone.now()),
        "period": filters.period.as_dict() if filters is not None else None,
        "freshness": freshness(sources),
    }
    meta.update(refresh_meta())
    return meta


def envelope(data, filters, sources, computed_at=None):
    return Response({"data": data, "meta": build_meta(filters, sources, computed_at)})
