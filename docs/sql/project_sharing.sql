-- 設計分享／輪流共編：唯讀分享連結、邀請連結、可編輯成員。
-- 後端用 service role 存取，授權在 routers/history.py 檢查，RLS 開著但不設政策（擋掉 anon）。
alter table public.projects
  add column if not exists share_token text unique,
  add column if not exists invite_token text unique;

create table if not exists public.project_members (
  project_id uuid not null references public.projects(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (project_id, user_id)
);
create index if not exists project_members_user_id_idx on public.project_members (user_id);
alter table public.project_members enable row level security;
