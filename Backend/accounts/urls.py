from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("admin/users", views.UserViewSet, basename="admin-users")
router.register("admin/roles", views.RoleViewSet, basename="admin-roles")

urlpatterns = [
    path("auth/token/", views.TokenView.as_view(), name="token"),
    path("auth/token/refresh/", views.RefreshView.as_view(), name="token-refresh"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("auth/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("admin/permissions/", views.PermissionListView.as_view(), name="permissions"),
    path("admin/audit-log/", views.AuditLogView.as_view(), name="audit-log"),
] + router.urls
