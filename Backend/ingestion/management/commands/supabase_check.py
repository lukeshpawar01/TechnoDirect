"""Check the live TD database connection on Supabase - read-only, nothing is written anywhere.

    python manage.py supabase_check --grant-sql    SQL to run once in Supabase > SQL Editor: a read-only login that can
                                                   read only the TD tables the dashboard uses
    python manage.py supabase_check                with the SUPABASE_DB_* login in .env: read-only? SSL? every table
                                                   and column present? row counts, latest order, Supabase's last refresh

Never prints the password.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from ingestion.connectors import supabase_queries as Q

ROLE = "td_dashboard_ro"


def grant_sql(schema="public", role=ROLE):
    tables = list(Q.READ_TABLES)
    out = [
        "-- TechnoDirect dashboard: a READ-ONLY login for the TD tables. Run once in Supabase > SQL Editor.",
        "-- Replace CHANGE_ME_STRONG_PASSWORD with a long random password (letters and digits only).",
        "-- Safe to run again (e.g. to change the password: edit it and re-run).",
        "do $$ begin",
        f"  if not exists (select from pg_roles where rolname = '{role}') then",
        f"    create role {role} with login password 'CHANGE_ME_STRONG_PASSWORD';",
        "  else",
        f"    alter role {role} with login password 'CHANGE_ME_STRONG_PASSWORD';",
        "  end if;",
        "end $$;",
        f"alter role {role} set default_transaction_read_only = on;",
        f"alter role {role} set statement_timeout = '120s';",
        f"grant usage on schema {Q.qident(schema)} to {role};",
    ]
    for t in tables:
        out.append(f"grant select on {Q.qident(schema)}.{Q.qident(t)} to {role};")
    arr = ", ".join(f"'{t}'" for t in tables)
    out += [
        "-- Tables with Row Level Security on: let this login read them (select only).",
        "do $$ declare t text; begin",
        f"  foreach t in array array[{arr}] loop",
        "    if exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace",
        f"               where n.nspname = '{schema}' and c.relname = t and c.relrowsecurity) then",
        f"      execute format('drop policy if exists td_dashboard_read on %I.%I', '{schema}', t);",
        f"      execute format('create policy td_dashboard_read on %I.%I for select to {role} using (true)', '{schema}', t);",
        "    end if;",
        "  end loop;",
        "end $$;",
    ]
    return "\n".join(out) + "\n"


class Command(BaseCommand):
    help = "Check the TD database connection on Supabase, or print the read-only login SQL (--grant-sql)."

    def add_arguments(self, parser):
        parser.add_argument("--grant-sql", action="store_true", help="Print the SQL that creates the read-only login")
        parser.add_argument("--schema", default="public")

    def handle(self, *args, **opts):
        if opts["grant_sql"]:
            self.stdout.write(grant_sql(opts["schema"]))
            return
        if "supabase" not in settings.DATABASES:
            raise CommandError("The Supabase login is not set in Backend/.env (SUPABASE_DB_HOST / SUPABASE_DB_USER / "
                               "SUPABASE_DB_PASSWORD are still REPLACE_ME).")
        problems = []
        ok = lambda msg: self.stdout.write(self.style.SUCCESS(f"  OK   {msg}"))  # noqa: E731
        bad = lambda msg: (problems.append(msg), self.stdout.write(self.style.ERROR(f"  FAIL {msg}")))  # noqa: E731
        try:
            cur = connections["supabase"].cursor()
            cur.execute("select current_user, current_schema()")
        except Exception as exc:  # noqa: BLE001
            hint = ""
            text = str(exc)
            if "password authentication failed" in text or "Tenant or user not found" in text:
                hint = (" - check SUPABASE_DB_USER is td_dashboard_ro.<project-ref> and the password matches the one in "
                        "supabase_readonly.sql")
            raise CommandError(f"Cannot connect: {type(exc).__name__}: {text.splitlines()[0][:300]}{hint}") from None
        user, schema = cur.fetchone()
        self.stdout.write(f"Connected as {user}, schema {schema}")

        cur.execute("show transaction_read_only")
        (ro,) = cur.fetchone()
        (ok if ro == "on" else bad)(f"read-only session ({ro})")
        # this PC -> Supabase link, as seen by the client (pg_stat_ssl on the server describes the pooler's own link
        # to Postgres, which is not ours)
        pgconn = getattr(connections["supabase"].connection, "pgconn", None)
        if pgconn is not None and getattr(pgconn, "ssl_in_use", False):
            ok("SSL encrypted")
        else:
            bad("connection is NOT encrypted (set SUPABASE_DB_SSLMODE=require)")

        cur.execute("select table_name, column_name from information_schema.columns where table_schema = current_schema()")
        have = {}
        for t, c in cur.fetchall():
            have.setdefault(t, set()).add(c)
        for t, cols in Q.READ_TABLES.items():
            if t not in have:
                bad(f"table {t}: missing or not granted (run supabase_readonly.sql)")
                continue
            miss = [c for c in cols if c not in have[t]]
            if miss:
                bad(f"table {t}: columns missing: {', '.join(miss)}")
        if not any(p.startswith("table ") for p in problems):
            ok(f"all {len(Q.READ_TABLES)} tables and their columns readable")

        for kind, (table, _cols) in Q.TABLES.items():
            try:
                cur.execute(f"select count(*) from ({Q.select_sql(kind)}) q")
                (n,) = cur.fetchone()
                (ok if n else bad)(f"{table}: {n:,} rows" + ("" if n else " - empty, or hidden by Row Level Security "
                                                                       "(re-run supabase_readonly.sql)"))
            except Exception as exc:  # noqa: BLE001
                bad(f"{table}: {str(exc).splitlines()[0][:200]}")
        try:
            cur.execute("select max(order_date) from orders")
            self.stdout.write(f"  Latest order date: {cur.fetchone()[0]}")
            cur.execute("select table_name, last_success_at from etl_watermark order by table_name")
            rows = cur.fetchall()
            if rows:
                self.stdout.write("  Supabase last refreshed (etl_watermark):")
                for t, at in rows:
                    self.stdout.write(f"    {t:<22} {at:%Y-%m-%d %H:%M} UTC" if at else f"    {t:<22} -")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"  (latest order / etl_watermark not readable: {str(exc).splitlines()[0][:120]})")

        if problems:
            raise CommandError(f"{len(problems)} problem(s) - see FAIL lines above.")
        self.stdout.write(self.style.SUCCESS("Ready: python manage.py run_sync supabase"))
