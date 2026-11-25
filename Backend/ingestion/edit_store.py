"""Keep what admins edit in the dashboard in Supabase, so it survives a new server (Render, a new PC, a lost disk).

Laid out like the dashboard: one Supabase schema ("folder") per module, one table per kind of record, with real columns
(ids, names, dates...) plus `_synced_at`, like the TD tables in `public`:

    region_asm_performance  targets, asms, rsms, asm_handovers, field_staff, tracked_distributors, target_forecasts
    distributors            distributors        (ASM, state, aliases set in the dashboard)
    mappings                regions, states, pincodes
    admin                   users, roles, audit_log, metric_definitions, reconciliation_refs
    pnl                     quarters            (the P&L inputs: revenue, returns, costs, % assumptions)
    admin (MBR)             mbr_reviews, mbr_items  (Monthly Business Review commentary, actions, tech, developments)

Everything else (retailers, orders, stock, BlueOrigin, ...) is rebuilt from the sources by the refresh, so it is not
copied. The login SUPABASE_EDITS_USER can only use these four schemas (deploy/supabase_edits.sql); it creates and
extends the tables itself, so a new field in the dashboard becomes a new column automatically.

  push()     local -> Supabase, only rows whose content changed (`_hash`); rows deleted locally are deleted
  restore()  Supabase -> a new, empty local database (or --force)
Push runs a few seconds after any change made through the dashboard (EditBackupMiddleware) and every 15 minutes
(ingestion/scheduler.py); restore runs by itself when the server starts on an empty database.
"""
import datetime as dt
import decimal
import hashlib
import json
import logging
import threading
from dataclasses import dataclass

from django.apps import apps
from django.conf import settings
from django.db import connections, transaction

log = logging.getLogger(__name__)

ALIAS = "supabase_edits"
CHUNK = 500

# (model, schema = dashboard module, table) in restore order (a record's links point to tables earlier in the list)
LAYOUT = [
    ("accounts.Role", "admin", "roles"),
    ("warehouse.Region", "mappings", "regions"),
    ("warehouse.State", "mappings", "states"),
    ("warehouse.Rsm", "region_asm_performance", "rsms"),
    ("warehouse.Asm", "region_asm_performance", "asms"),
    ("warehouse.Distributor", "distributors", "distributors"),
    ("warehouse.AsmAssignment", "region_asm_performance", "asm_handovers"),
    ("masters.ManualMapping", "mappings", "manual_mappings"),  # mappings given in chat, until proper data
    ("warehouse.FieldStaff", "region_asm_performance", "field_staff"),
    ("warehouse.Pincode", "mappings", "pincodes"),
    ("warehouse.TrackedDistributor", "region_asm_performance", "tracked_distributors"),
    ("warehouse.Target", "region_asm_performance", "targets"),
    ("warehouse.TargetSplit", "region_asm_performance", "incentive_sheet"),  # person-by-person KPI targets
    ("warehouse.TargetForecast", "region_asm_performance", "target_forecasts"),
    ("masters.MetricDefinition", "admin", "metric_definitions"),
    ("masters.ReconciliationRef", "admin", "reconciliation_refs"),
    ("accounts.User", "admin", "users"),
    ("accounts.AuditLog", "admin", "audit_log"),
    ("masters.PnlQuarter", "pnl", "quarters"),
    ("masters.MbrReview", "admin", "mbr_reviews"),  # Monthly Business Review (kept in admin: no new schema)
    ("masters.MbrItem", "admin", "mbr_items"),
]
SCHEMAS = sorted({s for _, s, _ in LAYOUT})
# also owned by the edits login: fixed sheets stored in Supabase (ingestion/reference_sheets.py)
SETUP_SCHEMAS = sorted(set(SCHEMAS) | {"reference"})
TRACKED = [m for m, _, _ in LAYOUT]
SKIP_M2M = {"groups", "user_permissions"}  # Django's built-in groups are not used (roles are)
PG_TYPES = {
    "BigAutoField": "bigint", "AutoField": "bigint", "BigIntegerField": "bigint", "IntegerField": "integer",
    "PositiveIntegerField": "integer", "PositiveSmallIntegerField": "integer", "SmallIntegerField": "integer",
    "ForeignKey": "bigint", "OneToOneField": "bigint", "BooleanField": "boolean", "DateField": "date",
    "DateTimeField": "timestamptz", "DecimalField": "numeric", "FloatField": "double precision", "JSONField": "jsonb",
    "UUIDField": "uuid",
}


def configured():
    return ALIAS in settings.DATABASES


@dataclass
class Spec:
    """One dashboard table <-> one Supabase table."""
    label: str
    schema: str
    table: str

    @property
    def model(self):
        return apps.get_model(self.label)

    @property
    def fields(self):
        return list(self.model._meta.concrete_fields)

    @property
    def m2m(self):
        return [f for f in self.model._meta.many_to_many if f.name not in SKIP_M2M]

    @property
    def columns(self):
        """[(column, postgres type)] - FKs keep their *_id name; many-to-many links are a jsonb list of ids."""
        cols = [(f.attname, PG_TYPES.get(f.get_internal_type(), "text")) for f in self.fields]
        return cols + [(f.name, "jsonb") for f in self.m2m]

    @property
    def qname(self):
        return f'"{self.schema}"."{self.table}"'


SPECS = [Spec(*row) for row in LAYOUT]


def _plain(v):
    if isinstance(v, (dt.datetime, dt.date, decimal.Decimal)):
        return str(v)
    return v


def local_rows(spec):
    """{id: (values in spec.columns order, hash)} for the dashboard's records of this kind."""
    model, fields, m2m = spec.model, spec.fields, spec.m2m
    qs = model.objects.order_by("pk")
    if m2m:
        qs = qs.prefetch_related(*[f.name for f in m2m])
    out = {}
    for obj in qs.iterator(chunk_size=2000) if not m2m else qs:
        vals = [f.value_from_object(obj) for f in fields]
        vals += [sorted(o.pk for o in getattr(obj, f.name).all()) for f in m2m]
        h = hashlib.sha1(json.dumps([_plain(v) for v in vals], sort_keys=True, default=str).encode()).hexdigest()
        out[obj.pk] = (vals, h)
    return out


# ----------------------------------------------------------------------------- Supabase side
class SupabaseState:
    """The module schemas in Supabase, through the edits login (raw SQL; never migrated by Django)."""

    def __init__(self, alias=ALIAS):
        self.alias = alias
        self._ensured = set()

    def _cur(self):
        return connections[self.alias].cursor()

    def ensure(self, spec):
        """Create the table / add new columns (the dashboard gained a field) - once per process."""
        if spec.label in self._ensured:
            return
        cols = ", ".join(f'"{c}" {t}' + (" PRIMARY KEY" if c == "id" else "") for c, t in spec.columns)
        with self._cur() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS {spec.qname} ({cols}, \"_hash\" text, "
                      f"\"_synced_at\" timestamptz DEFAULT now())")
            for col, typ in spec.columns:
                c.execute(f'ALTER TABLE {spec.qname} ADD COLUMN IF NOT EXISTS "{col}" {typ}')
            c.execute(f"ALTER TABLE {spec.qname} ENABLE ROW LEVEL SECURITY")  # nobody else via Supabase's API
        self._ensured.add(spec.label)

    def hashes(self, spec):
        self.ensure(spec)
        with self._cur() as c:
            c.execute(f'SELECT id, "_hash" FROM {spec.qname}')
            return dict(c.fetchall())

    def upsert(self, spec, rows):
        """rows: [(values in spec.columns order, hash)]"""
        from psycopg.types.json import Jsonb

        self.ensure(spec)
        cols = [c for c, _ in spec.columns]
        jcols = {i for i, (_c, t) in enumerate(spec.columns) if t == "jsonb"}
        names = ", ".join(f'"{c}"' for c in cols + ["_hash"])
        marks = ", ".join(["%s"] * (len(cols) + 1))
        sets = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols[1:] + ["_hash"]) + ', "_synced_at" = now()'
        sql = f"INSERT INTO {spec.qname} ({names}) VALUES ({marks}) ON CONFLICT (id) DO UPDATE SET {sets}"
        data = [[Jsonb(v) if i in jcols and v is not None else v for i, v in enumerate(vals)] + [h] for vals, h in rows]
        with self._cur() as c:
            for i in range(0, len(data), CHUNK):
                c.executemany(sql, data[i:i + CHUNK])

    def delete(self, spec, ids):
        with self._cur() as c:
            for i in range(0, len(ids), CHUNK):
                c.execute(f"DELETE FROM {spec.qname} WHERE id = ANY(%s)", [list(ids[i:i + CHUNK])])

    def rows(self, spec):
        """[{column: value}] of the Supabase copy."""
        self.ensure(spec)
        cols = [c for c, _ in spec.columns]
        names = ", ".join(f'"{x}"' for x in cols)
        with self._cur() as c:
            c.execute(f"SELECT {names} FROM {spec.qname}")
            return [dict(zip(cols, r)) for r in c.fetchall()]

    def counts(self):
        out = {}
        for spec in SPECS:
            self.ensure(spec)
            with self._cur() as c:
                c.execute(f"SELECT count(*) FROM {spec.qname}")
                out[f"{spec.schema}.{spec.table}"] = c.fetchone()[0]
        return out


def push(store=None):
    """Send what changed locally. Returns {"sent": n, "deleted": n, "tables": {schema.table: n}}."""
    if local_is_empty():
        # a new server whose restore has not happened yet: pushing would wipe the Supabase copy
        log.warning("edits backup skipped: this database has no users yet (restore from Supabase first)")
        return {"sent": 0, "deleted": 0, "tables": {}, "errors": {}, "skipped": "empty local database"}
    store = store or SupabaseState()
    sent = deleted = 0
    per = {}
    errors = {}
    for spec in SPECS:
        name = f"{spec.schema}.{spec.table}"
        try:
            local = local_rows(spec)
            remote = store.hashes(spec)
            send = [(vals, h) for pk, (vals, h) in local.items() if remote.get(pk) != h]
            gone = [pk for pk in remote if pk not in local]
            if len(remote) >= 5 and not local:
                # never empty a whole Supabase table from an empty local one (a half-restored server)
                errors[name] = f"local table is empty - kept the {len(remote)} rows in Supabase"
                continue
            if send:
                store.upsert(spec, send)
            if gone:
                store.delete(spec, gone)
        except Exception as exc:  # noqa: BLE001 - e.g. a new module's schema not created in Supabase yet
            errors[name] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
            if hasattr(store, "alias"):
                connections[store.alias].close()  # start the next table on a clean connection
            continue
        if send or gone:
            per[name] = len(send) + len(gone)
        sent, deleted = sent + len(send), deleted + len(gone)
    if per:
        log.info("edits backup: %s", per)
    if errors:
        log.warning("edits backup - not saved (re-run deploy/supabase_edits.sql in Supabase?): %s", errors)
    return {"sent": sent, "deleted": deleted, "tables": per, "errors": errors}


def local_is_empty():
    return not apps.get_model("accounts.User").objects.exists()


def restore(store=None, force=False):
    """Load the Supabase copy into the local database. Without force only into an empty one (no users yet)."""
    from django.core.management.color import no_style

    store = store or SupabaseState()
    if not force and not local_is_empty():
        return {"restored": 0, "skipped": "the local database already has users - use --force to overwrite"}
    counts = {}
    with transaction.atomic():
        for spec in SPECS:
            rows = store.rows(spec)
            if not rows:
                continue
            model, m2m = spec.model, spec.m2m
            names = {f.attname for f in spec.fields}
            objs = [model(**{k: v for k, v in r.items() if k in names}) for r in rows]
            if not model.objects.exists():
                model.objects.bulk_create(objs, batch_size=1000)
            else:
                for o in objs:
                    o.save()
            for f in m2m:  # many-to-many links (a user's region / state / ASM / distributor access)
                for r in rows:
                    getattr(model(pk=r["id"]), f.name).set(r.get(f.name) or [])
            counts[f"{spec.schema}.{spec.table}"] = len(rows)
        conn = connections["default"]  # Postgres: move id sequences past the restored ids (SQLite needs nothing)
        for stmt in conn.ops.sequence_reset_sql(no_style(), [s.model for s in SPECS]):
            with conn.cursor() as c:
                c.execute(stmt)
    log.info("edits restored from Supabase: %s", counts)
    return {"restored": sum(counts.values()), "tables": counts}


# ----------------------------------------------------------------------------- push soon after a change
_timer = None
_timer_lock = threading.Lock()
DEBOUNCE_SECONDS = 5


def _push_now():
    global _timer
    with _timer_lock:
        _timer = None
    try:
        push()
    except Exception:  # noqa: BLE001 - retried by the 15-minute check
        log.exception("edits backup failed")
    finally:
        connections.close_all()


def push_soon():
    """Push a few seconds from now (several quick edits = one push)."""
    global _timer
    if not configured():
        return
    with _timer_lock:
        if _timer is None:
            _timer = threading.Timer(DEBOUNCE_SECONDS, _push_now)
            _timer.daemon = True
            _timer.start()


class EditBackupMiddleware:
    """After a successful change through the API (POST / PUT / PATCH / DELETE), back the edits up to Supabase."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400
                and request.path.startswith("/api/") and configured()):
            push_soon()
        return response


def setup_sql():
    grants = "\n".join(
        f"create schema if not exists {s};\n"
        f"grant usage, create on schema {s} to td_dashboard_rw;\n"
        f"revoke all on schema {s} from anon, authenticated;" for s in SETUP_SCHEMAS)
    return f"""-- TechnoDirect dashboard: where the dashboard's own edits are kept, one folder (schema) per module:
--   {", ".join(SETUP_SCHEMAS)}  (reference = fixed sheets)
-- Run in Supabase > SQL Editor. The login td_dashboard_rw creates its tables there itself; it cannot touch anything
-- else (your TD tables in `public` included). Safe to run again.
-- First time only: replace CHANGE_ME_STRONG_PASSWORD (letters and digits). If the login already exists its password
-- is left as it is.
do $$ begin
  if not exists (select from pg_roles where rolname = 'td_dashboard_rw') then
    create role td_dashboard_rw with login password 'CHANGE_ME_STRONG_PASSWORD';
  end if;
end $$;
alter role td_dashboard_rw set statement_timeout = '120s';
{grants}
-- the first version kept everything in one table; it is replaced by the module folders above
drop table if exists dashboard.app_state;
drop schema if exists dashboard;
"""
