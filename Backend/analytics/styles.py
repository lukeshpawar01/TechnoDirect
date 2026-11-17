"""Style (article) codes for the Style filter.

The catalogue stores some styles with a colour, batch or case variant in the code: "OR35 Black", "OR99/B11",
"or10", "S101-BLACK,NAVY,GREY". Sales "by style" mean the base code (OR35, OR99, OR10, S101), so the filter works on
base codes and expands each one to every raw variant before matching order lines / inventory rows.
"""
import re

from django.core.cache import cache

_BASE = re.compile(r"[A-Z]*\d+[A-Z]?")


def base_style(raw):
    """'OR35 Black' -> 'OR35', 'OR99/B11' -> 'OR99', 'or10' -> 'OR10', 'S101-GREY' -> 'S101'."""
    s = (raw or "").strip().upper()
    m = _BASE.match(s)
    return m.group(0) if m else (s.split()[0] if s else "")


def _natural(code):
    m = re.match(r"([A-Z]*)(\d+)(.*)", code)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (code, 0, "")


def catalog():
    """{base code: {code, name, l1, l2, l3, variants}} - the latest launch names the style."""
    from .cache import cache_version

    key = f"styles:catalog:v{cache_version()}"  # rebuilt after every sync (new styles / launches)
    data = cache.get(key)
    if data is not None:
        return data
    from warehouse.models import OrderLine, Product

    data = {}
    rows = Product.objects.values_list("style", "name", "category_l1", "category_l2", "category_l3").order_by(
        "launched_on", "id")
    for style, name, l1, l2, l3 in rows:
        code = base_style(style)
        if not code:
            continue
        e = data.setdefault(code, {"code": code, "variants": set(), "exact": False})
        e["variants"].add(style)
        # the product stored under the bare code names the style (not a batch / colour variant like OR99/B11);
        # among equals, the latest launch wins
        exact = style.strip().upper() == code
        if exact or not e["exact"]:
            e.update(name=(name or "").strip(), l1=l1 or "", l2=l2 or "", l3=l3 or "", exact=exact or e["exact"])
    # order lines can carry a style the catalogue has not seen yet
    for style in OrderLine.objects.exclude(style="").values_list("style", flat=True).distinct():
        code = base_style(style)
        if code:
            data.setdefault(code, {"code": code, "variants": set(), "name": "", "l1": "", "l2": "", "l3": ""})[
                "variants"].add(style)
    for e in data.values():
        e["variants"] = sorted(e["variants"])
        e.pop("exact", None)
    data = dict(sorted(data.items(), key=lambda kv: _natural(kv[0])))
    cache.set(key, data, 60 * 60 * 6)
    return data


def expand(codes):
    """Base codes -> every raw style value stored for them (unknown codes match themselves)."""
    cat = catalog()
    out = set()
    for c in codes:
        c = base_style(c)
        out.add(c)
        out.update(cat.get(c, {}).get("variants", []))
    return sorted(out)


def options():
    """Filter options: one entry per base style."""
    return [{"code": e["code"], "name": e["name"], "l1": e["l1"], "l2": e["l2"], "l3": e["l3"]}
            for e in catalog().values()]
