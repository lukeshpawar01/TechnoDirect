"""Fixed ("static") sheets kept in Supabase, schema `reference`, so the dashboard reads them from there and not from
files on one PC (TD_Data/DATA, data/import). Written with the edits login (SUPABASE_EDITS_*), which owns this schema.

    reference._sheets            catalog: name, tab, table, kind, source file, headers, rows, loaded_at
    reference.<name>             a CSV / TSV sheet: one text column per sheet header (readable like the TD tables)
    reference.<name>__<tab>      a workbook tab, cell by cell: columns A, B, C... and "_row" = the Excel row number,
                                 so the workbook can be rebuilt exactly (the importers read some workbooks by position)

    python manage.py reference_sheet upload sales_team "data/import/sales_team/Master ASM Tracker.csv"
    python manage.py import_sales_team supabase:sales_team          <- any importer takes supabase:<name> as its file
Uploading again replaces the stored copy (e.g. next month's targets tab under a new name: asm_tracker_2026_12).
"""
import csv
import datetime as dt
import io
import json
import os
import re
import tempfile

from django.conf import settings
from django.db import connections, transaction

ALIAS = "supabase_edits"
SCHEMA = "reference"
CATALOG = f'"{SCHEMA}"."_sheets"'
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
CHUNK = 500


class ReferenceError(RuntimeError):
    pass


def configured():
    return ALIAS in settings.DATABASES


def _q(ident):
    return '"' + str(ident).replace('"', '""') + '"'


def _slug(text, limit=24):
    return (re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "tab")[:limit]


def _columns(headers):
    """Sheet headers -> unique Postgres column names (as written; blanks / repeats made unique, max 63 chars)."""
    out, seen = [], set()
    for i, h in enumerate(headers, 1):
        base = (str(h or "").strip() or f"column_{i}")[:58]
        name, n = base, 2
        while name.lower() in seen or name.startswith("_"):
            name, n = f"{base}_{n}", n + 1
        seen.add(name.lower())
        out.append(name)
    return out


def _letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ----------------------------------------------------------------------------- reading the source file
def read_file(path, formulas=False):
    """[(tab, kind, headers, rows)] - one entry for a CSV/TSV, one per tab for an .xlsx. formulas=True keeps a
    workbook's formulas as text ("=G4-G5") instead of the values Excel calculated."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".tsv", ".txt"):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
        delim = "\t" if ext == ".tsv" or text.count("\t") > text.count(",") else ","
        grid = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
        grid = [r for r in grid if any((c or "").strip() for c in r)]
        if not grid:
            raise ReferenceError(f"{os.path.basename(path)} is empty")
        headers = grid[0]
        rows = [list(r) + [""] * (len(headers) - len(r)) for r in grid[1:]]
        return [("", "table", headers, [r[:len(headers)] for r in rows])]
    if ext in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=not formulas)
        out = []
        for ws in wb.worksheets:
            width = ws.max_column or 1
            rows = []
            for r in ws.iter_rows(min_row=1, max_row=ws.max_row or 1, max_col=width, values_only=True):
                rows.append([_cell_text(v) for v in r])
            out.append((ws.title, "grid", [_letters(i) for i in range(1, width + 1)], rows))
        return out
    raise ReferenceError("Upload a .csv, .tsv or .xlsx file")


def _cell_text(v):
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return repr(v)  # keep "12.0" so it rebuilds as a float, as Excel stored it
    return str(v)


def _cell_value(s):
    """Text stored in Supabase -> the value openpyxl would have read (number / date / text)."""
    if s is None or s == "":
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d*(e[-+]?\d+)?|-?\d+e[-+]?\d+", s, re.I):
        return float(s)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?", s):
        return dt.datetime.fromisoformat(s)
    return s


# ----------------------------------------------------------------------------- Supabase
class SupabaseReference:
    def __init__(self, alias=ALIAS):
        self.alias = alias

    def _cur(self):
        return connections[self.alias].cursor()

    def ensure_catalog(self):
        with self._cur() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS {CATALOG} (name text NOT NULL, tab text NOT NULL DEFAULT '', "
                      "position integer, table_name text NOT NULL, kind text NOT NULL, source_file text, "
                      "headers jsonb, rows integer, loaded_at timestamptz DEFAULT now(), PRIMARY KEY (name, tab))")
            c.execute(f"ALTER TABLE {CATALOG} ENABLE ROW LEVEL SECURITY")

    def replace(self, name, source_file, parts):
        """Store the sheet (replacing a previous upload of the same name). parts = read_file()."""
        self.ensure_catalog()
        with transaction.atomic(using=self.alias), self._cur() as c:
            c.execute(f"SELECT table_name FROM {CATALOG} WHERE name = %s", [name])
            for (old,) in c.fetchall():
                c.execute(f"DROP TABLE IF EXISTS {_q(SCHEMA)}.{_q(old)}")
            c.execute(f"DELETE FROM {CATALOG} WHERE name = %s", [name])
            for pos, (tab, kind, headers, rows) in enumerate(parts):
                table = name if kind == "table" else f"{name}__{_slug(tab)}"[:63]
                cols = _columns(headers) if kind == "table" else headers
                qt = f"{_q(SCHEMA)}.{_q(table)}"
                c.execute(f"CREATE TABLE {qt} (\"_row\" integer PRIMARY KEY, "
                          + ", ".join(f"{_q(col)} text" for col in cols) + ', "_loaded_at" timestamptz DEFAULT now())')
                c.execute(f"ALTER TABLE {qt} ENABLE ROW LEVEL SECURITY")
                # a % in a column name ("Share %") must be doubled in a statement that has parameters
                sql = (f"INSERT INTO {qt.replace('%', '%%')} (\"_row\", {', '.join(_q(col).replace('%', '%%') for col in cols)}) "
                       f"VALUES (%s, {', '.join(['%s'] * len(cols))})")
                first = 2 if kind == "table" else 1  # the sheet row number (row 1 = headers for a CSV)
                data = [[first + i, *[(v if v != "" or kind == "table" else None) for v in r]] for i, r in enumerate(rows)]
                for i in range(0, len(data), CHUNK):
                    c.executemany(sql, data[i:i + CHUNK])
                c.execute(f"INSERT INTO {CATALOG} (name, tab, position, table_name, kind, source_file, headers, rows) "
                          "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                          [name, tab, pos, table, kind, source_file, json.dumps(headers), len(rows)])
        return [{"tab": tab, "table": f"{SCHEMA}.{(name if kind == 'table' else f'{name}__{_slug(tab)}'[:63])}",
                 "rows": len(rows)} for tab, kind, headers, rows in parts]

    def delete(self, name):
        """Drop a stored sheet (all its tabs) and its catalog entry. Returns the dropped table names."""
        self.ensure_catalog()
        with transaction.atomic(using=self.alias), self._cur() as c:
            c.execute(f"SELECT table_name FROM {CATALOG} WHERE name = %s", [name])
            tables = [t for (t,) in c.fetchall()]
            for t in tables:
                c.execute(f"DROP TABLE IF EXISTS {_q(SCHEMA)}.{_q(t)}")
            c.execute(f"DELETE FROM {CATALOG} WHERE name = %s", [name])
        return tables

    def catalog(self, name=None):
        self.ensure_catalog()
        with self._cur() as c:
            c.execute(f"SELECT name, tab, position, table_name, kind, source_file, headers, rows, loaded_at FROM {CATALOG}"
                      + (" WHERE name = %s" if name else "") + " ORDER BY name, position", [name] if name else [])
            keys = ["name", "tab", "position", "table_name", "kind", "source_file", "headers", "rows", "loaded_at"]
            return [dict(zip(keys, r)) for r in c.fetchall()]

    def grid(self, entry):
        """The stored rows of one sheet / tab, in order, as lists of text in header order."""
        headers = entry["headers"] if isinstance(entry["headers"], list) else json.loads(entry["headers"])
        cols = _columns(headers) if entry["kind"] == "table" else headers
        with self._cur() as c:
            c.execute(f"SELECT \"_row\", {', '.join(_q(col) for col in cols)} FROM {_q(SCHEMA)}.{_q(entry['table_name'])} "
                      "ORDER BY \"_row\"")
            return headers, c.fetchall()


def keep_columns(parts, keep):
    """Only the listed columns of a CSV sheet (every column with that header; a repeated header keeps all its
    copies). Used to leave personal details (phone, email, address) out of Supabase."""
    want = {k.strip().lower() for k in keep if k.strip()}
    out = []
    for tab, kind, headers, rows in parts:
        if kind != "table":
            raise ReferenceError("--columns works for CSV / TSV sheets only")
        idx = [i for i, h in enumerate(headers) if str(h or "").strip().lower() in want]
        missing = want - {str(headers[i]).strip().lower() for i in idx}
        if missing:
            raise ReferenceError(f"Columns not in the sheet: {', '.join(sorted(missing))}")
        out.append((tab, kind, [headers[i] for i in idx], [[r[i] for i in idx] for r in rows]))
    return out


def upload(name, path, store=None, columns=None, formulas=False):
    if not NAME_RE.match(name or ""):
        raise ReferenceError("Name: lower-case letters, digits and _ (e.g. sales_team, asm_tracker_2026_11)")
    if not os.path.isfile(path):
        raise ReferenceError(f"File not found: {path}")
    parts = read_file(path, formulas=formulas)
    if columns:
        parts = keep_columns(parts, columns)
    store = store or SupabaseReference()
    return store.replace(name, os.path.basename(path), parts)


def to_local_file(name, store=None):
    """Rebuild the stored sheet as a temporary CSV / XLSX file (what the importers read). Returns its path."""
    store = store or SupabaseReference()
    entries = store.catalog(name)
    if not entries:
        raise ReferenceError(f"No sheet '{name}' in Supabase (reference_sheet list shows what is stored)")
    if entries[0]["kind"] == "table":
        headers, rows = store.grid(entries[0])
        fd, path = tempfile.mkstemp(prefix=f"ref_{name}_", suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(headers)
            for r in rows:
                w.writerow([v if v is not None else "" for v in r[1:]])
        return path
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for e in entries:
        ws = wb.create_sheet(e["tab"][:31] or "Sheet1")
        headers, rows = store.grid(e)
        for r in rows:
            for ci, v in enumerate(r[1:], 1):
                val = _cell_value(v)
                if val is not None:
                    ws.cell(row=r[0], column=ci, value=val)
    fd, path = tempfile.mkstemp(prefix=f"ref_{name}_", suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


def resolve_file(arg):
    """An importer's file argument: a path as before, or supabase:<name> = the copy stored in Supabase."""
    if isinstance(arg, str) and arg.startswith("supabase:"):
        if not configured():
            raise ReferenceError("SUPABASE_EDITS_USER / SUPABASE_EDITS_PASSWORD are not set in Backend/.env")
        return to_local_file(arg.split(":", 1)[1].strip())
    return arg


def command_file(arg):
    """resolve_file for a management command: errors become CommandError."""
    from django.core.management.base import CommandError

    try:
        return resolve_file(arg)
    except ReferenceError as exc:
        raise CommandError(str(exc)) from None


def table_rows(name, store=None):
    """A stored CSV sheet as rows of {header: text} (like csv.DictReader), or None when no sheet has that name."""
    store = store or SupabaseReference()
    entries = store.catalog(name)
    if not entries:
        return None
    if entries[0]["kind"] != "table":
        raise ReferenceError(f"'{name}' is a workbook, not a sheet with column headers")
    headers, rows = store.grid(entries[0])
    return [{h: (v if v is not None else "") for h, v in zip(headers, r[1:])} for r in rows]
