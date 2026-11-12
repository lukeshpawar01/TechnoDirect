"""Helpers for reading .env values where placeholders mean "not configured"."""
import os

PLACEHOLDER = "REPLACE_ME"


def clean(value, default=""):
    """Return value stripped, or `default` if empty / placeholder."""
    if value is None:
        return default
    value = str(value).strip()
    if not value or PLACEHOLDER in value:
        return default
    return value


def env_str(name, default=""):
    return clean(os.environ.get(name), default)


def env_bool(name, default=False):
    v = env_str(name, "")
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def env_list(name, default=None):
    v = env_str(name, "")
    if not v:
        return list(default or [])
    return [x.strip() for x in v.split(",") if x.strip()]


def env_int(name, default=0):
    v = env_str(name, "")
    try:
        return int(v) if v else default
    except ValueError:
        return default


def parse_times(value, default="10:00,18:00"):
    """'10:00,18:00' -> [(10, 0), (18, 0)] (sorted, validated)."""
    out = []
    for part in (clean(value) or default).split(","):
        part = part.strip()
        if not part:
            continue
        hh, _, mm = part.partition(":")
        h, m = int(hh), int(mm or 0)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(f"Invalid SYNC_TIMES entry: {part}")
        out.append((h, m))
    return sorted(set(out))


def is_configured(*values):
    """True when every value is non-empty and not a placeholder."""
    return all(clean(v) for v in values)
