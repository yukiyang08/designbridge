-- 帳號點數：生圖類 API 每次扣 1 點；角色放 auth.users 的 app_metadata.role（'admin' 不扣點）。
-- 後端用 service role 存取；使用者只能讀自己的點數。
create table if not exists public.user_credits (
  user_id uuid primary key references auth.users(id) on delete cascade,
  credits integer not null default 20 check (credits >= 0),   -- 新帳號預設點數
  updated_at timestamptz not null default now()
);
alter table public.user_credits enable row level security;
drop policy if exists "read own credits" on public.user_credits;
create policy "read own credits" on public.user_credits for select using (auth.uid() = user_id);

-- 扣 amount 點（負數＝退點）；回傳剩餘點數，點數不夠回 null，管理員回 -1（不扣）
create or replace function public.consume_credit(uid uuid, amount integer default 1)
returns integer language plpgsql security definer set search_path = public as $$
declare remaining integer;
begin
  if (select raw_app_meta_data->>'role' from auth.users where id = uid) = 'admin' then
    return -1;
  end if;
  insert into user_credits (user_id) values (uid) on conflict do nothing;
  update user_credits set credits = credits - amount, updated_at = now()
   where user_id = uid and credits >= amount
  returning credits into remaining;
  return remaining;
end $$;
revoke execute on function public.consume_credit(uuid, integer) from public, anon, authenticated;

-- 第一個管理員手動設（之後可在 /admin 頁面改）：
-- update auth.users set raw_app_meta_data = raw_app_meta_data || '{"role":"admin"}' where email = 'you@example.com';

-- 名單制：app_metadata.role 為 admin/user 才能用，沒角色＝未開通（後端 get_user_id 回 403）。
