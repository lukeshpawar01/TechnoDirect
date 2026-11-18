"""Small parsing / name-matching helpers shared by the importers and the master-data tools."""
import datetime as dt
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = dt.timezone.utc
DATE_FORMATS = ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d", "%m/%d/%Y"]
TWO = Decimal("0.01")
WHOLESALE_SHARE = Decimal("0.60")  # selling price / MRP (retailers pay MRP less 40%)


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def nice_name(name):
    name = re.sub(r"\s+", " ", (name or "").strip())
    if name.isupper() or name.islower():
        name = " ".join(w if len(w) <= 2 and w.isupper() else w.capitalize() for w in name.split(" "))
    return name


def parse_dt(value, tz):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            d = dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return d.replace(tzinfo=tz)
    raise ValueError(f"Unrecognised date '{value}'")


def to_bool(value):
    return (value or "").strip().lower() in ("true", "1", "yes", "y", "t")


def to_dec(value):
    try:
        return Decimal(str(value or "0").replace(",", ""))
    except Exception:
        return Decimal("0")


def to_int(value):
    try:
        return int(float(str(value or "0").replace(",", "")))
    except ValueError:
        return 0


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:32] or "uncategorised"


def end_of_day(date_value, not_before):
    """Date-only milestone -> 23:59 IST that day, never before `not_before`."""
    if not date_value:
        return None
    d = dt.datetime.combine(date_value.date() if isinstance(date_value, dt.datetime) else date_value,
                            dt.time(23, 59), tzinfo=IST)
    return max(d, not_before) if not_before else d


def to_date(value):
    value = (value or "").strip()[:10]
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None
