-- 許可名單：管理員先填 email，對方第一次登入時自動開通成該角色，之後這筆就刪掉（routers/common.py）。
-- 只有後端 service role 讀寫：開 RLS 但不給 policy。
create table if not exists public.allowed_emails (
  email text primary key check (email = lower(email)),
  role text not null default 'user' check (role in ('user', 'admin')),
  added_at timestamptz not null default now()
);
alter table public.allowed_emails enable row level security;

notify pgrst, 'reload schema';
