-- 家具資料庫 v2：ikea_products 加上品牌、細分類、系列、商品編號、顏色、尺寸欄位，
-- 並讓 match_ikea_products 一起回傳。表名沿用 ikea_products（程式都用這個名字），現在也放其他品牌。
-- 在 Supabase 後台 SQL Editor 依序執行；執行完再跑 scripts/upload_ikea_to_supabase.py --upload --rebuild

-- 0. 先備份原本的查詢函式定義：執行這行，把結果另存成文字檔（要還原時貼回去執行）
select pg_get_functiondef(p.oid) from pg_proc p where p.proname = 'match_ikea_products';

-- 1. 新欄位（已存在就跳過）
alter table ikea_products
  add column if not exists brand        text default 'IKEA',
  add column if not exists subcategory  text,
  add column if not exists series       text,
  add column if not exists product_code text,
  add column if not exists color        text,
  add column if not exists width_cm     real,
  add column if not exists depth_cm     real,
  add column if not exists height_cm    real;

-- 2. 查詢函式：回傳欄位變了，要先刪掉再建立（參數名稱與預設行為不變，後端程式不用改）
drop function if exists match_ikea_products;

create function match_ikea_products(
  query_embedding  vector(512),
  filter_category  text  default '',
  match_count      int   default 3,
  match_threshold  float default 0.75
)
returns table (
  id bigint, name text, category text, subcategory text, brand text, series text, color text,
  price int, url text, image_url text, width_cm real, depth_cm real, height_cm real,
  similarity float
)
language sql stable
as $$
  select p.id::bigint, p.name, p.category, p.subcategory, p.brand, p.series, p.color,
         p.price::int, p.url, p.image_url, p.width_cm, p.depth_cm, p.height_cm,
         1 - (p.embedding <=> query_embedding) as similarity
  from ikea_products p
  where (filter_category = '' or p.category = filter_category)
    and 1 - (p.embedding <=> query_embedding) >= match_threshold
  order by p.embedding <=> query_embedding
  limit match_count;
$$;
