-- TechnoDirect dashboard: a READ-ONLY login for the TD tables. Run once in Supabase > SQL Editor.
-- Replace CHANGE_ME_STRONG_PASSWORD with a long random password (letters and digits only).
-- Safe to run again (e.g. to change the password: edit it and re-run).
do $$ begin
  if not exists (select from pg_roles where rolname = 'td_dashboard_ro') then
    create role td_dashboard_ro with login password 'CHANGE_ME_STRONG_PASSWORD';
  else
    alter role td_dashboard_ro with login password 'CHANGE_ME_STRONG_PASSWORD';
  end if;
end $$;
alter role td_dashboard_ro set default_transaction_read_only = on;
alter role td_dashboard_ro set statement_timeout = '120s';
grant usage on schema "public" to td_dashboard_ro;
grant select on "public"."distributors" to td_dashboard_ro;
grant select on "public"."customers" to td_dashboard_ro;
grant select on "public"."products" to td_dashboard_ro;
grant select on "public"."orders" to td_dashboard_ro;
grant select on "public"."sales" to td_dashboard_ro;
grant select on "public"."inventory_snapshot" to td_dashboard_ro;
grant select on "public"."loyalty_ledger" to td_dashboard_ro;
grant select on "public"."etl_watermark" to td_dashboard_ro;
-- Tables with Row Level Security on: let this login read them (select only).
do $$ declare t text; begin
  foreach t in array array['distributors', 'customers', 'products', 'orders', 'sales', 'inventory_snapshot', 'loyalty_ledger', 'etl_watermark'] loop
    if exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
               where n.nspname = 'public' and c.relname = t and c.relrowsecurity) then
      execute format('drop policy if exists td_dashboard_read on %I.%I', 'public', t);
      execute format('create policy td_dashboard_read on %I.%I for select to td_dashboard_ro using (true)', 'public', t);
    end if;
  end loop;
end $$;
