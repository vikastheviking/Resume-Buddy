-- 1. Drop the now-unused app_users table (from the earlier SQLite->Postgres migration,
-- superseded by Supabase Auth). Confirmed unused by any current code.
drop table if exists app_users;

-- 2. Extend the resumes table for optimization history (it already exists with
-- file_url/parsed_data/status from earlier planning - this adds what's needed to save
-- each optimization result without disturbing those columns).
alter table resumes add column if not exists jd_text text;
alter table resumes add column if not exists optimized_resume text;
alter table resumes add column if not exists actual_score int;
alter table resumes add column if not exists updated_score int;

-- Make sure user_id actually references auth.users and cascades on account deletion.
-- Safe to run again if this constraint already exists (the DO block just skips it).
do $$
begin
  if not exists (
    select 1 from information_schema.table_constraints
    where table_name = 'resumes' and constraint_name = 'resumes_user_id_fkey'
  ) then
    alter table resumes
      add constraint resumes_user_id_fkey
      foreign key (user_id) references auth.users(id) on delete cascade;
  end if;
end $$;

-- RLS: each user can only see/insert/delete their own history. The browser writes
-- directly to this table using the signed-in user's own session (not the service_role
-- key), so this is the only thing standing between one user's resumes and another's.
alter table resumes enable row level security;

drop policy if exists "own resumes select" on resumes;
create policy "own resumes select" on resumes
  for select using (auth.uid() = user_id);

drop policy if exists "own resumes insert" on resumes;
create policy "own resumes insert" on resumes
  for insert with check (auth.uid() = user_id);

drop policy if exists "own resumes delete" on resumes;
create policy "own resumes delete" on resumes
  for delete using (auth.uid() = user_id);
