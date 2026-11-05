# 部署與後台管理

前端放靜態網站平台，後端放一台常駐 VM，資料與登入沿用 Supabase。帳號分「管理員」與「一般」，一般帳號用點數限制生圖次數。

## 部署架構

| 部分 | 建議放置 | 規格 / 備註 |
| --- | --- | --- |
| 前端（Vue，`npm run build`） | Cloudflare Pages / Vercel / Netlify | 純靜態檔，免費額度即可 |
| 後端（FastAPI + LangGraph） | GCP Compute Engine 一台 VM | 至少 4 vCPU、16 GB RAM；GPU 非必要 |
| 資料庫、登入、圖片儲存 | Supabase（現有專案） | 不需搬移 |
| 生圖 | fal.ai | 依次計費，由點數限制用量 |
| Gemini | Vertex AI | VM 掛有 Vertex 權限的 service account，不上傳 `service-account.json` |

後端不能用 serverless（Vercel Functions、Lambda、會縮到 0 的 Cloud Run）：

- 啟動時要在本機載入 torch、Depth Anything V2、UPerNet、SAM 2、兩個 CLIP、bge-m3；CPU 機器光 vision 模型就要約 155 秒，每次冷啟動都要重付。
- 模型常駐記憶體，需要 8–16 GB。
- `artifacts/` 用本機硬碟存中間檔，需要持久硬碟。

只是給評審展示時，可改用 Hugging Face Spaces（Docker、16 GB CPU upgrade），HTTPS 自帶，但硬碟不持久。

## 上線檢查清單

- [ ] 後端啟動拿掉 `--reload`、只開 1 個 worker（每多一個 worker 就多載一份模型）：
      `uvicorn api:app --host 0.0.0.0 --port 8000 --workers 1`
- [ ] VM 前面放 Caddy 或 nginx 反向代理，提供 HTTPS
- [ ] 後端 `.env`：`CORS_ORIGINS=https://<前端網域>`、`API_PUBLIC_URL=https://<後端網域>`，其餘沿用 `FAL_KEY`、`HF_TOKEN`、`SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`PYTHONUTF8=1`
- [ ] 確認 `DESIGNBRIDGE_DEV_NO_AUTH` 沒有開
- [ ] 前端 build 時設 `VITE_API_BASE=https://<後端網域>`、`VITE_SUPABASE_URL`、`VITE_SUPABASE_ANON_KEY`
- [ ] `StyleSuggestions.vue` 的 `apiBase` 預設寫死 `http://localhost:8000`，確認父元件有傳值
- [ ] Supabase → Authentication → URL Configuration：Site URL 與 Redirect URLs 加上正式網域
- [ ] 執行 `docs/sql/credits.sql` 並設定第一個管理員（見下方）
- [ ] 下載 SAM 2 模型到 `model/sam2/checkpoints/sam2.1_hiera_tiny.pt`（不在 git 裡）
- [ ] fal.ai 後台設花費上限，當作點數之外的第二道保險
- [ ] 設 cron 定期刪 `artifacts/` 裡 N 天前的檔；設計結果在 Supabase Storage，缺檔時會自動補回

## 角色與點數

| 能做的事 | 管理員 | 一般 |
| --- | --- | --- |
| 使用所有設計功能 | 可 | 可 |
| 生圖扣點 | 不扣 | 每次 1 點（新帳號預設 20 點） |
| 進入 `/admin` 後台 | 可 | 不可（後端回 403） |
| 查看所有帳號（email、名稱、註冊與最後登入時間） | 可 | 不可 |
| 設定任一帳號的點數 | 可 | 不可 |
| 把別人設為管理員或改回一般 | 可（不能降級自己） | 不可 |
| 停用、刪除帳號 | 到 Supabase 後台操作 | 不可 |

扣點的 API（都會呼叫 fal.ai）：

- `POST /api/generate`：生成、換風格、細部微調
- `POST /api/move-furniture`：移動家具後重修
- `POST /api/photo-move`：照片上搬家具
- `POST /api/generate-panorama`：環景

規則：

- 先扣再執行；執行失敗（任何錯誤回應）自動退回 1 點。
- 點數不足回 402「點數不足，請聯絡管理員」，前端照常顯示錯誤訊息。
- 扣點在資料庫函式 `consume_credit` 裡一次完成，同時送出多個請求也不會扣成負數。
- 角色存在 Supabase 的 `app_metadata.role`，使用者自己改不到。前端的檢查只管頁面顯示，權限由後端把關。

## 設定步驟

1. Supabase → SQL Editor，貼上並執行 `docs/sql/credits.sql`（建 `user_credits` 表與 `consume_credit` 函式，可重複執行）。
2. 指定第一個管理員（該帳號要先用 Google 登入過一次）：
   ```sql
   update auth.users
      set raw_app_meta_data = raw_app_meta_data || '{"role":"admin"}'
    where email = 'you@example.com';
   ```
3. 重新整理個人專區，會出現「後台管理」入口，進入 `/admin`。
4. 之後新增管理員、調整點數都在 `/admin` 操作，不用再寫 SQL。

新帳號的預設點數改 `user_credits.credits` 的欄位預設值，同時改 `routers/admin.py` 的 `_DEFAULT_CREDITS`。

## API

| 方法 | 路徑 | 權限 | 說明 |
| --- | --- | --- | --- |
| GET | `/api/me` | 登入 | 回 `{role, credits}`；管理員的 `credits` 是 `null` |
| GET | `/api/admin/users?page=1&per_page=50` | 管理員 | 帳號列表（含角色、點數） |
| PATCH | `/api/admin/users/{id}` | 管理員 | body `{role?: "admin"\|"user", credits?: int}` |

## 常見問題

- **設了管理員但進不去 `/admin`**：後端每次都向 Supabase 查最新角色，不用重新登入；確認 SQL 的 email 跟登入帳號一致。
- **使用者說點數被扣但沒出圖**：失敗會自動退點。如果請求在執行中被中斷（例如伺服器重啟），點數不會退，請到 `/admin` 手動補回。
- **想看誰用了多少**：目前只記剩餘點數，沒有用量明細；需要時再加一張用量紀錄表。
