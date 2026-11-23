"""Analytics response cache keyed by (endpoint, user scope, filters, data version).

`bump_cache_version()` is called after every successful sync / derivation, which
invalidates every cached analytics response at once.
"""
import hashlib

from django.conf import settings
from django.core.cache import cache

VERSION_KEY = "analytics:data-version"


def cache_version():
    """The data version every cached page key carries. Kept in the DATABASE (SyncWatermark), not in the cache: each
    server process (the background service, the dev server) has its own cache, and a refresh run by one of them must
    retire the pages the other one cached too."""
    try:
        from ingestion.models import SyncWatermark

        v = SyncWatermark.objects.filter(key=VERSION_KEY).values_list("cursor", flat=True).first()
        if v and v.isdigit():
            return int(v)
    except Exception:  # noqa: BLE001 - e.g. during migrations: fall back to the cache
        pass
    v = cache.get(VERSION_KEY)
    if v is None:
        v = 1
        cache.set(VERSION_KEY, v, None)
    return v


def bump_cache_version():
    import time

    from django.utils import timezone

    v = int(time.time() * 1000)  # milliseconds: always higher than the last one, no read-modify-write race
    try:
        from ingestion.models import SyncWatermark

        SyncWatermark.put(VERSION_KEY, timezone.now(), cursor=str(v))
    except Exception:  # noqa: BLE001 - database busy: at least this process stops serving old pages
        pass
    cache.set(VERSION_KEY, v, None)


def analytics_key(name, filters, extra=""):
    raw = f"{name}|{filters.scope.signature()}|{filters.cache_signature()}|{extra}"
    return f"an:v{cache_version()}:{name}:{hashlib.sha1(raw.encode()).hexdigest()}"


def default_timeout():
    """Live until the next scheduled refresh (+ buffer); refresh_all bumps the version anyway."""
    from ingestion.schedule import seconds_until_next_refresh

    return seconds_until_next_refresh() + settings.ANALYTICS_CACHE_BUFFER_SECONDS


def get_or_compute(key, fn, timeout=None):
    data = cache.get(key)
    if data is None:
        data = fn()
        cache.set(key, data, timeout or default_timeout())
    return data
