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
    path("asm-tracker/executives/", views.ExecutivePerformanceView.as_view()),
    path("manual-mappings/", views.ManualMappingsView.as_view()),
    path("incentives/", views.IncentiveTrackerView.as_view()),
    path("incentives/retailers/", views.IncentiveRetailersView.as_view()),
    path("asm-tracker/asm/", views.AsmTrackerCreateView.as_view(kind="asm")),
    path("asm-tracker/distributor/", views.AsmTrackerCreateView.as_view(kind="distributor")),
    path("metrics/", views.MetricDictionaryView.as_view()),
    path("metrics/<str:code>/", views.MetricDictionaryView.as_view()),
    path("pnl/", views.PnlView.as_view()),
    path("pnl/quarters/", views.PnlQuarterView.as_view()),
    path("pnl/quarters/<str:start>/", views.PnlQuarterView.as_view()),
] + router.urls
