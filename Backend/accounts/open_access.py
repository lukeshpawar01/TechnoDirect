"""Open access (user, 2026-11-28): the dashboard has no login at all - every visitor gets full access.

Every request is authenticated as one built-in "Everyone" account: a master admin with all data, so every page,
export and admin tool works without signing in. It has no usable password, so nobody can sign in as it, and the
audit log shows its actions as "Everyone".

Switch: OPEN_ACCESS (default True). Set OPEN_ACCESS=False in .env to bring back email + password sign-in.
"""
from rest_framework.authentication import BaseAuthentication

PUBLIC_EMAIL = "everyone@open.local"
_cached_id = None


def public_user():
    global _cached_id
    from .models import User

    if _cached_id is not None:
        u = User.objects.filter(pk=_cached_id, is_active=True).first()
        if u:
            return u
    u = User.objects.filter(email=PUBLIC_EMAIL).first()
    if u is None:
        u = User(email=PUBLIC_EMAIL, full_name="Everyone", is_master_admin=True, scope_all=True)
        u.set_unusable_password()
        u.save()
    elif not (u.is_active and u.is_master_admin and u.scope_all):
        u.is_active, u.is_master_admin, u.scope_all = True, True, True
        u.save(update_fields=["is_active", "is_master_admin", "scope_all"])
    _cached_id = u.pk
    return u


class OpenAccessAuthentication(BaseAuthentication):
    """Every request is the built-in "Everyone" user (no token, no login)."""

    def authenticate(self, request):
        return public_user(), None
