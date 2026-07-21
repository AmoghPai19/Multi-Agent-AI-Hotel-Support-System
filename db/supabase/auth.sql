-- ============================================================================
--  db/supabase/auth.sql  —  Supabase-ONLY wiring
--
--  Apply this ONLY against your Supabase project (via the SQL editor or the
--  Supabase CLI), AFTER schema.sql. It references auth.users and auth.uid(),
--  which exist only on Supabase — that is why it is NOT in docker-compose's
--  local init scripts.
-- ============================================================================

-- 1) Real foreign key from our profile row to Supabase's managed user.
alter table public.guests
  add constraint fk_guests_auth_user
  foreign key (auth_user_id) references auth.users(id) on delete set null;

-- 2) Auto-create a guests profile row whenever someone signs up (and verifies).
--    SECURITY DEFINER lets the trigger insert into public.guests even though
--    the signup runs in Supabase's auth context.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.guests (auth_user_id, email, full_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'full_name', ''));
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 3) Row Level Security — defense in depth. Primary guest-scoping is enforced
--    in FastAPI (we inject the authenticated guest_id into queries), but with a
--    real per-user identity we ALSO let the database refuse cross-guest access.
--    Effective when the request's Supabase JWT is set on the DB session.
alter table public.reservations enable row level security;

create policy guest_owns_reservations on public.reservations
  for all
  using      (guest_id = (select id from public.guests where auth_user_id = auth.uid()))
  with check (guest_id = (select id from public.guests where auth_user_id = auth.uid()));

-- Policy chunks are readable only through the compliance path; lock down direct
-- guest access as well.
alter table public.policy_chunks enable row level security;
-- (No SELECT policy for the `authenticated` role => guests cannot read it directly.)
