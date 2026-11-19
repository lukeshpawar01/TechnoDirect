-- TechnoDirect dashboard: where the dashboard's own edits are kept, one folder (schema) per module:
--   admin, distributors, mappings, pnl, reference, region_asm_performance  (reference = fixed sheets)
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
create schema if not exists admin;
grant usage, create on schema admin to td_dashboard_rw;
revoke all on schema admin from anon, authenticated;
create schema if not exists distributors;
grant usage, create on schema distributors to td_dashboard_rw;
revoke all on schema distributors from anon, authenticated;
create schema if not exists mappings;
grant usage, create on schema mappings to td_dashboard_rw;
revoke all on schema mappings from anon, authenticated;
create schema if not exists pnl;
grant usage, create on schema pnl to td_dashboard_rw;
revoke all on schema pnl from anon, authenticated;
create schema if not exists reference;
grant usage, create on schema reference to td_dashboard_rw;
revoke all on schema reference from anon, authenticated;
create schema if not exists region_asm_performance;
grant usage, create on schema region_asm_performance to td_dashboard_rw;
revoke all on schema region_asm_performance from anon, authenticated;
-- the first version kept everything in one table; it is replaced by the module folders above
drop table if exists dashboard.app_state;
drop schema if exists dashboard;
