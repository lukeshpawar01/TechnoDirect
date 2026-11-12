import json
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import AuditLog


def snapshot(obj):
    """JSON-safe dict of a model instance (M2M as id lists)."""
    if obj is None:
        return None
    data = model_to_dict(obj)
    for k, v in list(data.items()):
        if isinstance(v, (list, tuple)):
            data[k] = [getattr(x, "pk", x) for x in v]
        elif k == "password":
            data[k] = "***"
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def _client_ip(request):
    if request is None:
        return None
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(request, action, obj=None, before=None, after=None, object_type=None, object_id=None, reason=""):
    user = getattr(request, "user", None) if request is not None else None
    if user is not None and not user.is_authenticated:
        user = None
    if not reason and request is not None:
        try:
            reason = (request.data.get("reason") if hasattr(request, "data") and hasattr(request.data, "get")
                      else "") or request.META.get("HTTP_X_AUDIT_REASON", "")
        except Exception:  # noqa: BLE001
            reason = ""
    if after is not None and not isinstance(after, (dict, list)):
        after = snapshot(after)
    return AuditLog.objects.create(
        user=user,
        user_email=getattr(user, "email", "") or "system",
        action=action,
        object_type=object_type or (obj._meta.label if obj is not None else ""),
        object_id=str(object_id if object_id is not None else (obj.pk if obj is not None else "")),
        before=json.loads(json.dumps(before, cls=DjangoJSONEncoder)) if before is not None else None,
        after=json.loads(json.dumps(after, cls=DjangoJSONEncoder)) if after is not None else None,
        reason=str(reason or "")[:255],
        ip=_client_ip(request),
    )


class AuditedModelMixin:
    """Mixin for ModelViewSets: writes AuditLog rows on create / update / destroy."""

    def perform_create(self, serializer):
        obj = serializer.save()
        log_action(self.request, "create", obj, after=snapshot(obj))

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        obj = serializer.save()
        log_action(self.request, "update", obj, before=before, after=snapshot(obj))

    def perform_destroy(self, instance):
        before = snapshot(instance)
        pk = instance.pk
        label = instance._meta.label
        instance.delete()
        log_action(self.request, "delete", None, before=before, object_type=label, object_id=pk)
