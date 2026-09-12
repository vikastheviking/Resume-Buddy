-- Resume-Buddy's own user store, backing engine/auth.py.
-- This is intentionally separate from Supabase Auth (auth.users) and from any
-- `profiles` table tied to it - this app manages its own accounts (password or
-- OTP-only) and only uses Supabase here as a persistent Postgres database,
-- accessed via the service_role key from the Python engine.
create table if not exists app_users (
  id bigserial primary key,
  email text unique not null,
  password_hash text not null,
  salt text not null,
  created_at timestamptz not null default now()
);

-- RLS stays enabled with zero policies: this blocks the anon/authenticated keys
-- entirely. Only the service_role key (used server-side by the engine) can read
-- or write this table, since service_role bypasses RLS by design.
alter table app_users enable row level security;
