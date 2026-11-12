"""CSV / XLSX export for list endpoints (`?export=csv|xlsx`, permission `export_data`)."""
import csv
import io
import json

from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

EXPORT_MAX_ROWS = 100_000


def _flatten(row, prefix=""):
    out = {}
    for k, v in row.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, list):
            out[key] = json.dumps(v, default=str) if any(isinstance(x, (dict, list)) for x in v) else ", ".join(
                str(x) for x in v)
        else:
            out[key] = v
    return out


def rows_to_response(rows, filename, fmt):
    rows = [_flatten(dict(r)) for r in rows]
    columns = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M")
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
        resp = HttpResponse(buf.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}_{stamp}.csv"'
        return resp
    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook(write_only=True)
        ws = wb.create_sheet(filename[:31])
        ws.append(columns)
        for r in rows:
            ws.append([_cell(r.get(c)) for c in columns])
        out = io.BytesIO()
        wb.save(out)
        resp = HttpResponse(out.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="{filename}_{stamp}.xlsx"'
        return resp
    raise ValidationError({"export": "must be csv or xlsx"})


def _cell(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def check_export_permission(request):
    if not request.user.has_code("export_data"):
        raise PermissionDenied("Permission 'export_data' required.")


class ExportListMixin:
    """For ListAPIView / ModelViewSet: `?export=csv|xlsx` returns all filtered rows as a file."""

    export_filename = "export"

    def list(self, request, *args, **kwargs):
        fmt = request.query_params.get("export")
        if fmt:
            check_export_permission(request)
            qs = self.filter_queryset(self.get_queryset())[:EXPORT_MAX_ROWS]
            data = self.get_serializer(qs, many=True).data
            return rows_to_response(data, self.export_filename, fmt)
        return super().list(request, *args, **kwargs)
