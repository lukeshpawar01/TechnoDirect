from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/health/", health),
    path("api/", include("accounts.urls")),
    path("api/", include("analytics.urls")),
    path("api/masters/", include("masters.urls")),
    path("api/", include("assistant.urls")),
]


def spa_index(request):
    """The built dashboard (Frontend/dist/index.html) for every non-API path, so deep links survive a reload."""
    index = Path(settings.FRONTEND_DIST) / "index.html"
    if not index.is_file():
        raise Http404
    resp = FileResponse(open(index, "rb"), content_type="text/html")
    resp["Cache-Control"] = "no-cache"  # always pick up a new build
    return resp


if settings.FRONTEND_DIST:
    urlpatterns.append(re_path(r"^(?!api/|django-admin/|static/).*$", spa_index))
