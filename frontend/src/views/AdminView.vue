<script setup>
/** 後台管理：帳號角色與生圖點數。權限由後端 require_admin 把關，這頁只是介面。 */
import { onMounted, ref } from 'vue'
import { authFetch, jsonFetch } from '@/config/api'
import AppNav from '@/components/shell/AppNav.vue'
import sceneBg from '@/assets/figma/room-bg.png'

const users = ref([])
const page = ref(1)
const hasMore = ref(false)
const loading = ref(false)
const error = ref('')
const query = ref('')
const savingId = ref(null)
const summary = ref({ days: 30, total_cost_usd: 0, unassigned: null })
const openId = ref(null)
const events = ref([])

async function toggleUsage(u) {
  if (openId.value === u.id) { openId.value = null; return }
  openId.value = u.id
  events.value = []
  const res = await authFetch(`/api/admin/users/${u.id}/usage`)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) { error.value = data.detail || `${res.status}`; return }
  events.value = data.events
}

const usd = v => `$${Number(v || 0).toFixed(Number(v) < 1 ? 4 : 2)}`
const num = v => Number(v || 0).toLocaleString()
const secs = v => (v == null ? '—' : `${Number(v).toFixed(1)}s`)

async function load(p = page.value) {
  loading.value = true
  error.value = ''
  try {
    const res = await authFetch(`/api/admin/users?page=${p}`)
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `${res.status}`)
    users.value = data.users.map(u => ({ ...u, draftCredits: u.credits, draftRole: u.role }))
    page.value = p
    hasMore.value = data.has_more
    summary.value = { days: data.days, total_cost_usd: data.total_cost_usd, unassigned: data.unassigned }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function save(u) {
  savingId.value = u.id
  error.value = ''
  try {
    const res = await jsonFetch(`/api/admin/users/${u.id}`, { role: u.draftRole, credits: Number(u.draftCredits) }, 'PATCH')
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status}`)
    u.role = u.draftRole
    u.credits = Number(u.draftCredits)
  } catch (e) {
    error.value = e.message
  } finally {
    savingId.value = null
  }
}

const dirty = u => u.role !== u.draftRole || u.credits !== Number(u.draftCredits)
const visible = () => {
  const q = query.value.trim().toLowerCase()
  return q ? users.value.filter(u => `${u.email} ${u.name || ''}`.toLowerCase().includes(q)) : users.value
}
const fmt = t => (t ? new Date(t).toLocaleString('zh-TW', { dateStyle: 'short', timeStyle: 'short' }) : '—')

// 許可名單：只列還沒登入過的 email，開通後後端會移出
const allowlist = ref([])
const allowEmail = ref('')
const allowRole = ref('user')
const allowSaving = ref(false)

async function loadAllow() {
  const res = await authFetch('/api/admin/allowlist')
  const data = await res.json().catch(() => ({}))
  if (!res.ok) { error.value = data.detail || `${res.status}`; return }
  allowlist.value = data.entries
}

async function addAllow() {
  const email = allowEmail.value.trim().toLowerCase()
  // 已經登入過的帳號直接在下面表格改角色就好
  const existing = users.value.find(u => (u.email || '').toLowerCase() === email)
  if (existing) { error.value = `${email} 已經登入過，請直接在下方表格把角色改成「一般」或「管理員」`; return }
  allowSaving.value = true
  error.value = ''
  try {
    const res = await jsonFetch('/api/admin/allowlist', { email, role: allowRole.value })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status}`)
    allowEmail.value = ''
    await loadAllow()
  } catch (e) {
    error.value = e.message
  } finally {
    allowSaving.value = false
  }
}

async function removeAllow(a) {
  const res = await authFetch(`/api/admin/allowlist/${encodeURIComponent(a.email)}`, { method: 'DELETE' })
  if (res.ok) allowlist.value = allowlist.value.filter(x => x.email !== a.email)
}

onMounted(() => { load(1); loadAllow() })
</script>

<template>
  <div class="db-scene admin" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />

    <div class="db-card admin-card">
      <h1 class="title">後台管理</h1>
      <p class="lead">只有許可名單內的帳號能使用。一般帳號預設 20 點，生成、移動家具、環景每次扣 1 點，失敗會退回；管理員不限次數。</p>

      <section class="allow" aria-labelledby="allow-title">
        <h2 id="allow-title" class="sub">許可名單</h2>
        <p class="hint">加入 email 後，對方用這個 Google 帳號第一次登入就會自動開通。</p>
        <form class="allow-form" @submit.prevent="addAllow">
          <input v-model="allowEmail" class="db-input" type="email" required placeholder="name@gmail.com" aria-label="要加入的 email">
          <select v-model="allowRole" class="db-input" aria-label="開通後的角色">
            <option value="user">一般</option>
            <option value="admin">管理員</option>
          </select>
          <button class="db-btn db-btn--sm" :disabled="allowSaving">{{ allowSaving ? '加入中…' : '加入名單' }}</button>
        </form>
        <ul v-if="allowlist.length" class="allow-list">
          <li v-for="a in allowlist" :key="a.email">
            <span class="email">{{ a.email }}</span>
            <span class="name">{{ a.role === 'admin' ? '管理員' : '一般' }} · 等待第一次登入</span>
            <button class="db-btn db-btn--ghost db-btn--sm" @click="removeAllow(a)">移除</button>
          </li>
        </ul>
      </section>

      <div class="toolbar">
        <input v-model="query" class="db-input" type="search" placeholder="搜尋 email 或名稱（本頁）" aria-label="搜尋帳號">
        <button class="db-btn db-btn--ghost db-btn--sm" :disabled="loading" @click="load()">重新整理</button>
      </div>

      <p class="lead">
        近 {{ summary.days }} 天估計總花費 <strong>{{ usd(summary.total_cost_usd) }}</strong>
        <span v-if="summary.unassigned">（其中 {{ usd(summary.unassigned.cost_usd) }} 對不到帳號，例如本機免登入）</span>
        · 金額依單價估算，以 Vertex / fal 帳單為準
      </p>

      <p v-if="error" class="db-error" role="alert">{{ error }}</p>

      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>帳號</th><th>角色</th><th>點數</th><th>近 {{ summary.days }} 天用量</th><th>註冊</th><th>最後登入</th><th></th></tr>
          </thead>
          <tbody>
            <template v-for="u in visible()" :key="u.id">
            <tr>
              <td data-label="帳號">
                <div class="email">{{ u.email }}</div>
                <div v-if="u.name" class="name">{{ u.name }}</div>
              </td>
              <td data-label="角色">
                <select v-model="u.draftRole" class="db-input" :aria-label="`${u.email} 的角色`">
                  <option value="pending">未開通</option>
                  <option value="user">一般</option>
                  <option value="admin">管理員</option>
                </select>
              </td>
              <td data-label="點數">
                <input v-model="u.draftCredits" class="db-input credits" type="number" min="0"
                  :aria-label="`${u.email} 的點數`">
                <div v-if="u.draftRole === 'admin'" class="name">管理員不扣點</div>
              </td>
              <td data-label="用量">
                <button v-if="u.usage" class="usage-btn" :aria-expanded="openId === u.id" @click="toggleUsage(u)">
                  <span class="cost">{{ usd(u.usage.cost_usd) }}</span>
                  <span class="name">{{ num(u.usage.tokens) }} tokens · {{ u.usage.images }} 張圖 · {{ secs(u.usage.duration_s) }}</span>
                </button>
                <span v-else class="name">—</span>
              </td>
              <td data-label="註冊" class="time">{{ fmt(u.created_at) }}</td>
              <td data-label="最後登入" class="time">{{ fmt(u.last_sign_in_at) }}</td>
              <td class="row-action">
                <button class="db-btn db-btn--sm" :disabled="!dirty(u) || savingId === u.id" @click="save(u)">
                  {{ savingId === u.id ? '儲存中…' : '儲存' }}
                </button>
              </td>
            </tr>
            <tr v-if="openId === u.id" class="detail">
              <td colspan="7">
                <table class="events">
                  <thead>
                    <tr><th>時間</th><th>功能</th><th>模型</th><th>輸入 / 輸出 token</th><th>圖</th><th>耗時（排隊）</th><th>花費</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(e, i) in events" :key="i">
                      <td data-label="時間" class="time">{{ fmt(e.created_at) }}</td>
                      <td data-label="功能">{{ e.route }}</td>
                      <td data-label="模型" class="name">{{ e.model }}</td>
                      <td data-label="token">{{ e.kind === 'llm' ? `${num(e.prompt_tokens)} / ${num(e.completion_tokens)}` : '—' }}</td>
                      <td data-label="圖">{{ e.images ?? '—' }}</td>
                      <td data-label="耗時">{{ secs(e.duration_s) }}<span v-if="e.queue_s != null" class="name">（{{ secs(e.queue_s) }}）</span></td>
                      <td data-label="花費" class="cost">{{ usd(e.cost_usd) }}</td>
                    </tr>
                    <tr v-if="!events.length"><td colspan="7" class="empty">載入中…</td></tr>
                  </tbody>
                </table>
              </td>
            </tr>
            </template>
            <tr v-if="!loading && !visible().length"><td colspan="7" class="empty">沒有帳號</td></tr>
          </tbody>
        </table>
      </div>

      <div class="pager">
        <button class="db-btn db-btn--ghost db-btn--sm" :disabled="page === 1 || loading" @click="load(page - 1)">上一頁</button>
        <span>第 {{ page }} 頁</span>
        <button class="db-btn db-btn--ghost db-btn--sm" :disabled="!hasMore || loading" @click="load(page + 1)">下一頁</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin { display: flex; flex-direction: column; padding-bottom: 3rem; }
.admin-card { margin-top: 1.25rem; padding: 2.5rem clamp(1.5rem, 3vw, 2.75rem); }

.title {
  margin: 0 0 0.4rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.9rem;
  color: var(--db-text);
}
.lead { margin: 0 0 1.5rem; color: var(--db-text-soft); font-size: 0.9rem; }

.toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1rem; }
.toolbar .db-input { max-width: 320px; }

.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th, td { padding: 0.7rem 0.6rem; border-bottom: 1px solid var(--db-line); text-align: left; vertical-align: middle; }
th { color: var(--db-text-soft); font-weight: 500; white-space: nowrap; }
.email { color: var(--db-text); }
.name, .time { color: var(--db-text-soft); font-size: 0.8rem; }
.time { white-space: nowrap; }
.credits { width: 6rem; font-family: var(--db-font-num); }
.empty { text-align: center; color: var(--db-text-soft); }
.cost { font-family: var(--db-font-num); color: var(--db-text); }

.allow { margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--db-line); }
.sub { margin: 0 0 0.25rem; font-size: 1.05rem; font-weight: 500; color: var(--db-text); }
.hint { margin: 0 0 0.75rem; color: var(--db-text-soft); font-size: 0.85rem; }
.allow-form { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; }
.allow-form input { flex: 1 1 240px; max-width: 320px; }
.allow-form select { width: auto; }
.allow-list { list-style: none; margin: 0.9rem 0 0; padding: 0; font-size: 0.88rem; }
.allow-list li { display: flex; gap: 0.75rem; align-items: center; padding: 0.5rem 0; border-top: 1px solid var(--db-line); }
.allow-list .name { margin-right: auto; }
.usage-btn {
  display: flex; flex-direction: column; align-items: flex-start; gap: 0.1rem;
  padding: 0; border: 0; background: none; font: inherit; text-align: left; cursor: pointer;
}
.usage-btn:hover .cost { text-decoration: underline; }
.detail > td { padding: 0 0 1rem; background: var(--db-paper); }
.events { font-size: 0.8rem; }
.events th, .events td { padding: 0.45rem 0.6rem; }

.pager { display: flex; gap: 0.75rem; align-items: center; justify-content: flex-end; margin-top: 1rem; color: var(--db-text-soft); }

/* 手機：表格改成每個帳號一張卡，欄名用 data-label 標在值上方 */
@media (max-width: 640px) {
  .admin-card { padding: 1.5rem 1rem; }
  .toolbar .db-btn { flex: none; white-space: nowrap; }
  table, tbody, tr, td { display: block; }
  thead { display: none; }
  tbody > tr:not(.detail) {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.6rem 0.75rem;
    padding: 0.9rem 0; border-bottom: 1px solid var(--db-line);
  }
  td { padding: 0; border: 0; }
  td[data-label]::before { content: attr(data-label); display: block; margin-bottom: 0.15rem; font-size: 0.72rem; color: var(--db-text-soft); }
  td[data-label="帳號"]::before { display: none; }
  td[data-label="帳號"], td[data-label="用量"], .row-action, .empty { grid-column: 1 / -1; }
  .row-action .db-btn { width: 100%; }
  .detail > td { padding: 0 0 0.75rem; }
  .events tbody > tr:not(.detail) { padding: 0.6rem 0.5rem; }
}
</style>
