"""Analytics response cache keyed by (endpoint, user scope, filters, data version).

`bump_cache_version()` is called after every successful sync / derivation, which
invalidates every cached analytics response at once.
"""
import hashlib

from django.conf import settings
from django.core.cache import cache

VERSION_KEY = "analytics:data-version"


def cache_version():
    v = cache.get(VERSION_KEY)
    if v is None:
        v = 1
        cache.set(VERSION_KEY, v, None)
    return v


def bump_cache_version():
    try:
        cache.incr(VERSION_KEY)
    except ValueError:
        cache.set(VERSION_KEY, 2, None)


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
