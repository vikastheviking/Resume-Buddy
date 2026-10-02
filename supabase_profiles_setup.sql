-- One-time Supabase setup for Resume-Buddy accounts. Run in the Supabase SQL Editor.
-- Safe to run again: every statement is idempotent.
--
-- The server's /api/auth/check-availability route reads this table to tell Sign In
-- (email must already exist) apart from Create Account (email and phone must be free).
-- Without it, that check fails and nobody can sign in or sign up.

-- 1. One profile row per Supabase Auth user.
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  phone text,
  created_at timestamptz not null default now()
);

create index if not exists profiles_email_idx on public.profiles (email);
create index if not exists profiles_phone_idx on public.profiles (phone);

-- 2. RLS: a user can read only their own row. The server's availability check uses the
-- service_role key, which bypasses RLS.
alter table public.profiles enable row level security;

drop policy if exists "own profile select" on public.profiles;
create policy "own profile select" on public.profiles
  for select using (auth.uid() = id);

-- 3. Keep profiles in sync with auth.users. Full name and phone come from the
-- options.data passed to signInWithOtp on Create Account (raw_user_meta_data).
-- Emails are stored lowercase because the server looks them up lowercase.
create or replace function public.handle_auth_user_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, phone)
  values (
    new.id,
    lower(new.email),
    nullif(new.raw_user_meta_data ->> 'full_name', ''),
    nullif(new.raw_user_meta_data ->> 'phone', '')
  )
  on conflict (id) do update
    set email = excluded.email,
        full_name = coalesce(excluded.full_name, public.profiles.full_name),
        phone = coalesce(excluded.phone, public.profiles.phone);
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_auth_user_change();

drop trigger if exists on_auth_user_email_updated on auth.users;
create trigger on_auth_user_email_updated
  after update of email on auth.users
  for each row execute function public.handle_auth_user_change();

-- 4. Backfill users created before this trigger existed. Otherwise they get
-- "No account found with this email" on Sign In.
insert into public.profiles (id, email, full_name, phone)
select
  u.id,
  lower(u.email),
  nullif(u.raw_user_meta_data ->> 'full_name', ''),
  nullif(u.raw_user_meta_data ->> 'phone', '')
from auth.users u
on conflict (id) do update
  set email = excluded.email,
      full_name = coalesce(public.profiles.full_name, excluded.full_name),
      phone = coalesce(public.profiles.phone, excluded.phone);
