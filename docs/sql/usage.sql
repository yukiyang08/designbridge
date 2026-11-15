-- 每次 Gemini / fal 呼叫的用量與估計花費（designbridge/core/usage.py 寫入）。
-- 只有後端 service role 讀寫：開 RLS 但不給 policy。
create table if not exists public.usage_events (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete set null,   -- null＝對不到帳號（本機免登入、背景預熱）
  created_at timestamptz not null default now(),
  route text,                       -- 觸發的 API 路徑
  kind text not null,               -- llm / image
  model text,
  prompt_tokens integer,
  completion_tokens integer,        -- 含 Gemini 思考 token（同樣按輸出計費）
  images integer,
  duration_s real,                  -- 呼叫總耗時（秒）
  queue_s real,                     -- 其中在 fal 排隊等待的秒數；LLM 沒有
  cost_usd numeric(12, 6) not null default 0
);
create index if not exists usage_events_user_time on public.usage_events (user_id, created_at desc);
alter table public.usage_events enable row level security;

-- 後台用：每個帳號 since 之後的總用量
create or replace function public.usage_summary(since timestamptz)
returns table (user_id uuid, llm_calls bigint, tokens bigint, images bigint, duration_s real, cost_usd numeric)
language sql stable set search_path = public as $$
  select user_id,
         count(*) filter (where kind = 'llm'),
         coalesce(sum(coalesce(prompt_tokens, 0) + coalesce(completion_tokens, 0)), 0),
         coalesce(sum(images), 0),
         coalesce(sum(duration_s), 0)::real,
         coalesce(sum(cost_usd), 0)
    from usage_events
   where created_at >= since
   group by user_id;
$$;
revoke execute on function public.usage_summary(timestamptz) from public, anon, authenticated;

notify pgrst, 'reload schema';
