from django.urls import path

from .views.distributors import DistributorDetailView, DistributorsView, TerritoryView
from .views.funnel import FunnelView, RetailerDetailView, RetailerListView
from .views.health import DataHealthView, FilterOptionsView, SyncTriggerView
from .views.orders import OrderDetailView, OrderListView, OrdersSummaryView
from .views.overview import OverviewView
from .views.products import InventoryItemsView, InventoryView, ProductsView, ProductTreeView
from .views.retention import RetentionView

urlpatterns = [
    path("meta/filters/", FilterOptionsView.as_view()),
    path("overview/", OverviewView.as_view()),
    path("funnel/", FunnelView.as_view()),
    path("retailers/", RetailerListView.as_view()),
    path("retailers/<int:pk>/", RetailerDetailView.as_view()),
    path("distributors/", DistributorsView.as_view()),
    path("distributors/<int:pk>/", DistributorDetailView.as_view()),
    path("territory/", TerritoryView.as_view()),
    path("orders/summary/", OrdersSummaryView.as_view()),
    path("orders/", OrderListView.as_view()),
    path("orders/<int:pk>/", OrderDetailView.as_view()),
    path("products/", ProductsView.as_view()),
    path("products/tree/", ProductTreeView.as_view()),
    path("inventory/", InventoryView.as_view()),
    path("inventory/items/", InventoryItemsView.as_view()),
    path("retention/", RetentionView.as_view()),
    path("data-health/", DataHealthView.as_view()),
    path("data-health/sync/", SyncTriggerView.as_view()),
]
