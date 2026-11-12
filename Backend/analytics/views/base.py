from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts.permissions import HasPerm

from ..cache import analytics_key, get_or_compute
from ..envelope import envelope
from ..export import check_export_permission, rows_to_response
from ..filters import parse_filters


class AnalyticsView(APIView):
    """GET -> {data, meta}. Subclasses implement compute(filters, request, **kwargs).

    Responses are cached per (endpoint, user scope, filters, data version) until the
    next scheduled refresh. `?export=csv|xlsx` exports `data[export_key]`.
    """

    permission_code = None
    sources = ["medusa", "payu"]
    export_key = None
    pii_sensitive = False

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm(self.permission_code)()]

    def cache_extra(self, request, **kwargs):
        extra = f"{sorted(kwargs.items())}|{request.query_params.get('group_by', '')}"
        if self.pii_sensitive:
            extra += f"|pii={request.user.has_code('view_pii')}"
        return extra

    def compute(self, f, request, **kwargs):
        raise NotImplementedError

    def get(self, request, **kwargs):
        f = parse_filters(request)
        key = analytics_key(self.__class__.__name__, f, self.cache_extra(request, **kwargs))

        def _calc():
            return {"data": self.compute(f, request, **kwargs),
                    "computed_at": timezone.localtime().isoformat(timespec="seconds")}

        payload = get_or_compute(key, _calc)
        fmt = request.query_params.get("export")
        if fmt:
            check_export_permission(request)
            rows = payload["data"]
            for part in (request.query_params.get("table") or self.export_key or "").split("."):
                if part and isinstance(rows, dict):
                    rows = rows.get(part, [])
            if isinstance(rows, dict):
                rows = [rows]
            return rows_to_response(rows or [], self.__class__.__name__.replace("View", "").lower(), fmt)
        return envelope(payload["data"], f, self.sources, payload["computed_at"])
