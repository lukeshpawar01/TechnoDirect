from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from warehouse.models import Asm, Distributor, Region, State

from .models import PERMISSION_CODES, AuditLog, Role, User
from .scope import get_scope


def scope_dict(user):
    if user.is_master_admin or user.scope_all:
        return {"all": True, "regions": [], "states": [], "asms": [], "distributors": []}
    return {
        "all": False,
        "regions": list(user.scope_regions.values_list("id", flat=True)),
        "states": list(user.scope_states.values_list("id", flat=True)),
        "asms": list(user.scope_asms.values_list("id", flat=True)),
        "distributors": list(user.scope_distributors.values_list("id", flat=True)),
    }


class MeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "is_master_admin", "role", "permissions", "scope"]

    def get_role(self, obj):
        return {"id": obj.role_id, "name": obj.role.name} if obj.role_id else None

    def get_permissions(self, obj):
        return obj.permission_codes

    def get_scope(self, obj):
        return get_scope(obj).as_dict() if not obj.has_full_scope else scope_dict(obj)


class ScopeField(serializers.Field):
    """{all:bool, regions:[id], states:[id], asms:[id], distributors:[id]}"""

    def to_representation(self, user):
        return scope_dict(user)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("scope must be an object")
        out = {"all": bool(data.get("all", False))}
        for key, model in (("regions", Region), ("states", State), ("asms", Asm), ("distributors", Distributor)):
            ids = data.get(key) or []
            if not isinstance(ids, list):
                raise serializers.ValidationError({key: "must be a list of ids"})
            ids = [int(i) for i in ids]
            found = set(model.objects.filter(id__in=ids).values_list("id", flat=True))
            missing = [i for i in ids if i not in found]
            if missing:
                raise serializers.ValidationError({key: f"unknown ids {missing}"})
            out[key] = ids
        return out


class UserAdminSerializer(serializers.ModelSerializer):
    role_id = serializers.PrimaryKeyRelatedField(
        source="role", queryset=Role.objects.all(), allow_null=True, required=False
    )
    scope = ScopeField(source="*", required=False)
    password = serializers.CharField(write_only=True, required=False, validators=[validate_password])
    is_master_admin = serializers.BooleanField(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "is_active", "is_master_admin", "role_id", "role_name",
                  "scope", "last_login", "password"]
        read_only_fields = ["last_login"]

    def validate_email(self, v):
        return v.strip().lower()

    def _apply_scope(self, user, scope):
        if scope is None:
            return
        user.scope_all = scope.get("all", False)
        user.save(update_fields=["scope_all"])
        user.scope_regions.set(scope.get("regions", []))
        user.scope_states.set(scope.get("states", []))
        user.scope_asms.set(scope.get("asms", []))
        user.scope_distributors.set(scope.get("distributors", []))

    def _pop_scope(self, validated):
        keys = ("all", "regions", "states", "asms", "distributors")
        if not any(k in validated for k in keys):
            return None
        return {k: validated.pop(k) for k in keys if k in validated}

    def create(self, validated):
        scope = self._pop_scope(validated)
        password = validated.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "required"})
        user = User.objects.create_user(password=password, **validated)
        self._apply_scope(user, scope)
        return user

    def update(self, instance, validated):
        scope = self._pop_scope(validated)
        password = validated.pop("password", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()
        self._apply_scope(instance, scope)
        return instance


class RoleSerializer(serializers.ModelSerializer):
    user_count = serializers.IntegerField(read_only=True)
    permissions = serializers.ListField(child=serializers.CharField(), required=False)

    class Meta:
        model = Role
        fields = ["id", "name", "description", "permissions", "user_count"]

    def validate_permissions(self, value):
        bad = [c for c in value if c not in PERMISSION_CODES]
        if bad:
            raise serializers.ValidationError(f"Unknown permission codes: {bad}")
        return sorted(set(value))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get("user_count") is None:
            data["user_count"] = instance.users.count()
        return data


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ["id", "at", "user_email", "action", "object_type", "object_id", "before", "after", "reason"]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(validators=[validate_password])


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(validators=[validate_password])
