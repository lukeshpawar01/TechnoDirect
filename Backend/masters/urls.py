from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("targets", views.TargetViewSet, basename="targets")
router.register("asms", views.AsmViewSet, basename="asms")
router.register("pincodes", views.PincodeViewSet, basename="pincodes")
router.register("regions", views.RegionViewSet, basename="regions")
router.register("states", views.StateViewSet, basename="states")
router.register("reconciliation", views.ReconciliationViewSet, basename="reconciliation")

urlpatterns = [
    path("asm-tracker/", views.AsmTrackerView.as_view()),
    path("asm-tracker/upload/", views.AsmTrackerUploadView.as_view()),
    path("metrics/", views.MetricDictionaryView.as_view()),
    path("metrics/<str:code>/", views.MetricDictionaryView.as_view()),
] + router.urls
