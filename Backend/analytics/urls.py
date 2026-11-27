from django.urls import path

from .views.blueorigin import BoHierarchyView, BoPotentialView, BoRetailerListView, BoSummaryView
from .views.distributors import (DistributorDetailView, DistributorInsightsView, DistributorNetworkView,
                                 DistributorsView, TerritoryRetailersView, TerritoryView)
from .views.growth import GrowthView
from .views.funnel import FunnelView, RetailerDetailView, RetailerListView, RfmView, SegmentTrendView
from .views.loyalty import LoyaltyView
from .views.health import DataHealthView, DataVersionView, FilterOptionsView, SyncTriggerView
from .views.fulfilment import FulfilmentFlowView
from .views.orders import OrderDetailView, OrderListView, OrderRetailersView, OrdersSummaryView
from .views.overview import OverviewView
from .views.products import InventoryItemsView, InventoryOosStylesView, InventoryView, ProductsView, ProductTreeView
from .views.retention import RetentionView
from .views.settlement import SettlementDistributorDetailView, SettlementDistributorsView, SettlementOrderListView, SettlementSummaryView
from .views.trends import MomTrendView

from .views.runrate import RunRateView
from .views.mbr import MbrScorecardView

from .views.inventory_matrix import InventoryMatrixView, InventoryRunRateView
from .views.fullset import FullSetImpactView
from .views.best_sellers import BestSellersByAreaView

urlpatterns = [
    path("meta/filters/", FilterOptionsView.as_view()),
    path("meta/data-version/", DataVersionView.as_view()),
    path("overview/", OverviewView.as_view()),
    path("overview/run-rate/", RunRateView.as_view()),
    path("mbr/", MbrScorecardView.as_view()),
    path("trends/mom/", MomTrendView.as_view()),
    path("funnel/", FunnelView.as_view()),
    path("retailers/", RetailerListView.as_view()),
    path("retailers/rfm/", RfmView.as_view()),
    path("retailers/segment-trend/", SegmentTrendView.as_view()),
    path("retailers/<int:pk>/", RetailerDetailView.as_view()),
    path("blueorigin/summary/", BoSummaryView.as_view()),
    path("blueorigin/hierarchy/", BoHierarchyView.as_view()),
    path("blueorigin/retailers/", BoRetailerListView.as_view()),
    path("blueorigin/potential/", BoPotentialView.as_view()),
    path("settlements/summary/", SettlementSummaryView.as_view()),
    path("settlements/distributors/", SettlementDistributorsView.as_view()),
    path("settlements/distributors/<int:pk>/", SettlementDistributorDetailView.as_view()),
    path("settlements/orders/", SettlementOrderListView.as_view()),
    path("distributors/", DistributorsView.as_view()),
    path("distributors/insights/", DistributorInsightsView.as_view()),
    path("distributors/network/", DistributorNetworkView.as_view()),
    path("distributors/<int:pk>/", DistributorDetailView.as_view()),
    path("territory/", TerritoryView.as_view()),
    path("territory/retailers/", TerritoryRetailersView.as_view()),
    path("orders/summary/", OrdersSummaryView.as_view()),
    path("orders/flow/", FulfilmentFlowView.as_view()),
    path("orders/", OrderListView.as_view()),
    path("orders/retailers/", OrderRetailersView.as_view()),
    path("orders/<int:pk>/", OrderDetailView.as_view()),
    path("products/", ProductsView.as_view()),
    path("products/tree/", ProductTreeView.as_view()),
    path("products/best-sellers/", BestSellersByAreaView.as_view()),
    path("inventory/", InventoryView.as_view()),
    path("inventory/items/", InventoryItemsView.as_view()),
    path("inventory/oos-styles/", InventoryOosStylesView.as_view()),
    path("inventory/matrix/", InventoryMatrixView.as_view()),
    path("inventory/run-rate/", InventoryRunRateView.as_view()),
    path("inventory/fullset-impact/", FullSetImpactView.as_view()),
    path("retention/", RetentionView.as_view()),
    path("growth/", GrowthView.as_view()),
    path("loyalty/", LoyaltyView.as_view()),
    path("data-health/", DataHealthView.as_view()),
    path("data-health/sync/", SyncTriggerView.as_view()),
]
