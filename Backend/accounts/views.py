from django.db.models import Count
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from analytics.export import ExportListMixin

from .audit import AuditedModelMixin, log_action, snapshot
from .models import PERMISSIONS, AuditLog, Role, User
from .permissions import HasPerm
from .serializers import (
    AuditLogSerializer,
    ChangePasswordSerializer,
    MeSerializer,
    ResetPasswordSerializer,
    RoleSerializer,
    UserAdminSerializer,
)


class TokenView(TokenObtainPairView):
    """POST {email, password} -> {access, refresh}"""

    def post(self, request, *args, **kwargs):
        if isinstance(request.data, dict) and "email" in request.data:
            request.data["email"] = str(request.data["email"]).strip().lower()
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    pass


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)


class ChangePasswordView(APIView):
    def post(self, request):
        s = ChangePasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if not request.user.check_password(s.validated_data["old_password"]):
            return Response({"old_password": ["Incorrect password."]}, status=400)
        request.user.set_password(s.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        log_action(request, "change_password", request.user)
        return Response({"detail": "Password changed."})


class UserViewSet(AuditedModelMixin, ExportListMixin, viewsets.ModelViewSet):
    serializer_class = UserAdminSerializer
    permission_classes = [IsAuthenticated, HasPerm("manage_users")]
    export_filename = "users"
    filter_backends = [OrderingFilter]
    ordering_fields = ["email", "full_name", "last_login", "is_active", "date_joined"]

    def get_queryset(self):
        qs = User.objects.select_related("role").prefetch_related(
            "scope_regions", "scope_states", "scope_asms", "scope_distributors"
        )
        q = self.request.query_params.get("search")
        if q:
            qs = qs.filter(email__icontains=q) | qs.filter(full_name__icontains=q)
        return qs.order_by("email")

    def perform_update(self, serializer):
        inst = serializer.instance
        if inst.is_master_admin and inst != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Master admin can only be edited by itself.")
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied

        if instance.is_master_admin:
            raise PermissionDenied("The master admin cannot be deleted.")
        if instance == self.request.user:
            raise PermissionDenied("You cannot delete yourself.")
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        if user.is_master_admin and user != request.user:
            return Response({"detail": "Master admin password can only be changed by itself."}, status=403)
        s = ResetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user.set_password(s.validated_data["new_password"])
        user.save(update_fields=["password"])
        log_action(request, "reset_password", user)
        return Response({"detail": "Password reset."})


class RoleViewSet(AuditedModelMixin, viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated, HasPerm("manage_users")]
    pagination_class = None

    def get_queryset(self):
        return Role.objects.annotate(user_count=Count("users")).order_by("name")

    def perform_destroy(self, instance):
        if instance.users.exists():
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"detail": "Role is assigned to users; reassign them first."})
        super().perform_destroy(instance)


class PermissionListView(APIView):
    permission_classes = [IsAuthenticated, HasPerm("manage_users")]

    def get(self, request):
        return Response([{"code": c, "label": l, "group": g} for c, l, g in PERMISSIONS])


class AuditLogView(ExportListMixin, generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, HasPerm("manage_users")]
    export_filename = "audit_log"
    filter_backends = [OrderingFilter]
    ordering_fields = ["at", "user_email", "action", "object_type"]

    def get_queryset(self):
        qs = AuditLog.objects.all()
        p = self.request.query_params
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(user_email__icontains=s) | qs.filter(object_type__icontains=s) | qs.filter(
                action__icontains=s) | qs.filter(reason__icontains=s)
        if p.get("object_type"):
            qs = qs.filter(object_type__icontains=p["object_type"])
        if p.get("action"):
            qs = qs.filter(action=p["action"])
        if p.get("user"):
            qs = qs.filter(user_email__icontains=p["user"])
        if p.get("date_from"):
            qs = qs.filter(at__date__gte=p["date_from"])
        if p.get("date_to"):
            qs = qs.filter(at__date__lte=p["date_to"])
        return qs.order_by("-at")


__all__ = ["snapshot", "status"]
