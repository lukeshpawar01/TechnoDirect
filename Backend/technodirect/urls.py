from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/health/", health),
    path("api/", include("accounts.urls")),
    path("api/", include("analytics.urls")),
    path("api/masters/", include("masters.urls")),
]
