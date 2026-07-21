-- ============================================================================
--  roles.sql  —  Least-privilege database roles
--
--  CONCEPT — least privilege: the application never connects as the all-powerful
--  owner. Reads use a role that can ONLY read; writes use a role that can write
--  a few tables and CANNOT delete anything or change the schema. If the app (or
--  the LLM behind it) is ever tricked, the damage is capped by these grants —
--  not by the model's good behaviour.
--
--  Dev passwords below are intentionally simple and are for LOCAL ONLY.
--  In production these are managed secrets (and on Supabase, the platform
--  manages the built-in roles). Never commit real passwords.
-- ============================================================================

-- Read-only role: lookups, availability checks, RAG retrieval.
do $$ begin
  if not exists (select from pg_roles where rolname = 'app_readonly') then
    create role app_readonly login password 'app_readonly_dev_pw';
  end if;
end $$;
grant connect on database hotel to app_readonly;
grant usage on schema public to app_readonly;
grant select on all tables in schema public to app_readonly;
-- Also cover tables created in the future:
alter default privileges in schema public grant select on tables to app_readonly;

-- Writer role: can write booking + conversation tables only.
do $$ begin
  if not exists (select from pg_roles where rolname = 'app_writer') then
    create role app_writer login password 'app_writer_dev_pw';
  end if;
end $$;
grant connect on database hotel to app_writer;
grant usage on schema public to app_writer;
grant select, insert, update on
    reservations,
    reservation_status_history,
    guests,
    conversations,
    messages,
    audit_logs
  to app_writer;
-- Writers need to use the sequences behind the bigserial id columns:
grant usage, select on all sequences in schema public to app_writer;

-- DELIBERATELY no DELETE grant anywhere, and no rights on policy_* tables:
--   * cancellations are status changes, not row deletes (kept for audit)
--   * policy content is written by a separate admin ingestion path
