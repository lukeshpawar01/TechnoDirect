from rest_framework.permissions import SAFE_METHODS, BasePermission

AUTHENTICATED = "__authenticated__"


def HasPerm(code, read=None):
    """DRF permission class factory.

    `HasPerm("manage_targets")` -> user must hold that code (master admin holds all).
    `HasPerm("manage_alerts", read=AUTHENTICATED)` -> GET/HEAD/OPTIONS only need login.
    `HasPerm("manage_targets", read="view_overview")` -> different code for reads.
    """

    class _HasPerm(BasePermission):
        message = f"Permission '{code}' required."

        def has_permission(self, request, view):
            user = request.user
            if not user or not user.is_authenticated:
                return False
            needed = code
            if read is not None and request.method in SAFE_METHODS:
                needed = read
            if needed == AUTHENTICATED:
                return True
            if needed != code:
                self.message = f"Permission '{needed}' required."
            return user.has_code(needed)

    _HasPerm.__name__ = f"HasPerm_{code}"
    return _HasPerm


class IsMasterAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_master_admin)
