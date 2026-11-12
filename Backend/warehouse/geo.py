"""Reference geography used when a source gives only a pincode.

The India Post PIN system is hierarchical: the first 3 digits (sorting district) identify the
state for almost every pincode. This is the fallback until the Medusa `pincode` table
(pincode -> district, state) is connected; a state reported by a source row always wins.

Regions are the business zones from the strategic review. They are defaults only:
admins edit them on Admin > Mappings, and re-imports never overwrite an existing state's region.
"""

# code -> (state name, default region code)
STATES = {
    "KA": ("Karnataka", "SOUTH1"),
    "TS": ("Telangana", "SOUTH2"),
    "AP": ("Andhra Pradesh", "SOUTH2"),
    "TN": ("Tamil Nadu", "SOUTH3"),
    "KL": ("Kerala", "SOUTH3"),
    "PY": ("Puducherry", "SOUTH3"),
    "OD": ("Odisha", "EAST"),
    "WB": ("West Bengal", "EAST"),
    "BR": ("Bihar", "EAST"),
    "JH": ("Jharkhand", "EAST"),
    "CG": ("Chhattisgarh", "EAST"),
    "AS": ("Assam", "EAST"),
    "AR": ("Arunachal Pradesh", "EAST"),
    "ML": ("Meghalaya", "EAST"),
    "MN": ("Manipur", "EAST"),
    "MZ": ("Mizoram", "EAST"),
    "NL": ("Nagaland", "EAST"),
    "TR": ("Tripura", "EAST"),
    "SK": ("Sikkim", "EAST"),
    "AN": ("Andaman and Nicobar Islands", "EAST"),
    "MH": ("Maharashtra", "WEST"),
    "GA": ("Goa", "WEST"),
    "GJ": ("Gujarat", "WEST"),
    "MP": ("Madhya Pradesh", "WEST"),
    "RJ": ("Rajasthan", "NORTH"),
    "DL": ("Delhi", "NORTH"),
    "HR": ("Haryana", "NORTH"),
    "PB": ("Punjab", "NORTH"),
    "CH": ("Chandigarh", "NORTH"),
    "HP": ("Himachal Pradesh", "NORTH"),
    "JK": ("Jammu and Kashmir", "NORTH"),
    "LA": ("Ladakh", "NORTH"),
    "UP": ("Uttar Pradesh", "NORTH"),
    "UK": ("Uttarakhand", "NORTH"),
}

REGIONS = {
    "SOUTH1": "South 1 (Karnataka)",
    "SOUTH2": "South 2 (Telugu States)",
    "SOUTH3": "South 3 (TN & Kerala)",
    "EAST": "East",
    "WEST": "West",
    "NORTH": "North",
}

# (first 3 digits from, to inclusive, state code). Later entries override earlier ones.
_RANGES = [
    (110, 110, "DL"), (121, 136, "HR"), (140, 159, "PB"), (160, 160, "CH"), (171, 177, "HP"),
    (180, 193, "JK"), (194, 194, "LA"), (201, 285, "UP"), (246, 249, "UK"), (262, 263, "UK"),
    (301, 345, "RJ"), (360, 396, "GJ"), (400, 445, "MH"), (403, 403, "GA"), (450, 488, "MP"),
    (490, 497, "CG"), (500, 509, "TS"), (515, 535, "AP"), (560, 591, "KA"), (600, 643, "TN"),
    (670, 695, "KL"), (700, 743, "WB"), (737, 737, "SK"), (744, 744, "AN"), (751, 770, "OD"),
    (781, 788, "AS"), (790, 792, "AR"), (793, 794, "ML"), (795, 795, "MN"), (796, 796, "MZ"),
    (797, 798, "NL"), (799, 799, "TR"), (800, 855, "BR"),
    (813, 816, "JH"), (822, 822, "JH"), (825, 829, "JH"), (831, 835, "JH"),
]
_PREFIX = {}
for lo, hi, code in _RANGES:
    for p in range(lo, hi + 1):
        _PREFIX[p] = code

_NAME_TO_CODE = {name.lower(): code for code, (name, _) in STATES.items()}
_NAME_TO_CODE.update({"orissa": "OD", "pondicherry": "PY", "new delhi": "DL", "nct of delhi": "DL",
                      "j&k": "JK", "jammu & kashmir": "JK", "uttaranchal": "UK", "chattisgarh": "CG",
                      "andaman & nicobar islands": "AN"})


def is_valid_pincode(pin):
    pin = (pin or "").strip()
    return len(pin) == 6 and pin.isdigit() and pin[0] != "0"


def state_code_for_pincode(pin):
    """State code for a 6-digit pincode, or None when invalid / unknown."""
    if not is_valid_pincode(pin):
        return None
    return _PREFIX.get(int(pin[:3]))


def state_code_for_name(name):
    return _NAME_TO_CODE.get((name or "").strip().lower())
