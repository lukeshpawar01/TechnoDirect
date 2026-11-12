"""Row-level data scope.

A user's scope is either "all" or the UNION of the listed regions / states / ASMs /
distributors. Every analytics query passes through `apply_scope` with a field mapping
describing where those dimensions live on the queried model.
"""
import hashlib

from django.db.models import Q

# Field mappings for the common models (dimension -> lookup path of the FK id).
ORDER_DIMS = {"region": "region_id", "state": "state_id", "asm": "asm_id", "distributor": "distributor_id"}
RETAILER_DIMS = ORDER_DIMS
RETAILER_MONTH_DIMS = ORDER_DIMS
CRM_DIMS = ORDER_DIMS
DISTRIBUTOR_DIMS = {"region": "region_id", "state": "state_id", "asm": "asm_id", "distributor": "id"}
INVENTORY_DIMS = {
    "region": "distributor__region_id",
    "state": "distributor__state_id",
    "asm": "distributor__asm_id",
    "distributor": "distributor_id",
}
LINE_DIMS = {
    "region": "order__region_id",
    "state": "order__state_id",
    "asm": "order__asm_id",
    "distributor": "order__distributor_id",
}
STATE_DIMS = {"region": "region_id", "state": "id"}
REGION_DIMS = {"region": "id"}
ASM_DIMS = {"region": "region_id", "asm": "id"}


class UserScope:
    def __init__(self, user):
        self.user = user
        self.all = bool(user is None or user.has_full_scope)
        if self.all:
            self.regions = self.states = self.asms = self.distributors = []
        else:
            self.regions = list(user.scope_regions.values_list("id", flat=True))
            self.states = list(user.scope_states.values_list("id", flat=True))
            self.asms = list(user.scope_asms.values_list("id", flat=True))
            self.distributors = list(user.scope_distributors.values_list("id", flat=True))

    def as_dict(self):
        return {
            "all": self.all,
            "regions": self.regions,
            "states": self.states,
            "asms": self.asms,
            "distributors": self.distributors,
        }

    def signature(self):
        if self.all:
            return "all"
        raw = f"r{sorted(self.regions)}s{sorted(self.states)}a{sorted(self.asms)}d{sorted(self.distributors)}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def q(self, mapping):
        """Q object restricting to this scope; None means unrestricted."""
        if self.all:
            return None
        q = Q(pk__in=[])  # matches nothing
        for dim, ids in (("region", self.regions), ("state", self.states), ("asm", self.asms),
                         ("distributor", self.distributors)):
            field = mapping.get(dim)
            if ids and field:
                q |= Q(**{f"{field}__in": ids})
        return q


def get_scope(user):
    """Cached per-request scope object (stored on the user instance)."""
    if user is None:
        return UserScope(None)
    cached = getattr(user, "_td_scope", None)
    if cached is None:
        cached = UserScope(user)
        user._td_scope = cached
    return cached


def apply_scope(qs, user, mapping):
    q = get_scope(user).q(mapping)
    return qs if q is None else qs.filter(q)
