<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const API_BASE = 'http://localhost:8000'
const records = ref([])
const loading = ref(true)
const error = ref('')
const selected = ref(null)

// 批量模式
const batchMode = ref(false)
const checkedIds = ref(new Set())
const deleting = ref(false)

// 只看收藏——收藏是在預算估計那一步標記的，這裡只是把它們濾出來看
const favoritesOnly = ref(false)
const favoritingIds = ref(new Set())
const visibleRecords = computed(
  () => favoritesOnly.value ? records.value.filter(r => r.favorited) : records.value
)

const checkedCount = computed(() => checkedIds.value.size)
const allChecked = computed(() =>
  visibleRecords.value.length > 0 && visibleRecords.value.every(r => checkedIds.value.has(r.task_id))
)

async function toggleFavorite(r) {
  const next = !r.favorited
  const ids = new Set(favoritingIds.value); ids.add(r.task_id); favoritingIds.value = ids
  try {
    const res = await fetch(`${API_BASE}/api/history/${encodeURIComponent(r.task_id)}/favorite`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ favorited: next }),
    })
    if (!res.ok) throw new Error(res.status)
    r.favorited = next
  } catch {
    alert('收藏失敗，請稍後再試')
  } finally {
    const s = new Set(favoritingIds.value); s.delete(r.task_id); favoritingIds.value = s
  }
}

function toggleBatchMode() {
  batchMode.value = !batchMode.value
  checkedIds.value = new Set()
}

function toggleCheck(id) {
  const s = new Set(checkedIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  checkedIds.value = s
}

function toggleAll() {
  if (allChecked.value) {
    checkedIds.value = new Set()
  } else {
    checkedIds.value = new Set(visibleRecords.value.map(r => r.task_id))
  }
}

async function deleteSelected() {
  if (!checkedCount.value) return
  if (!confirm(`確定要刪除選取的 ${checkedCount.value} 筆紀錄嗎？`)) return
  deleting.value = true
  try {
    const ids = [...checkedIds.value]
    const res = await fetch(`${API_BASE}/api/history?${ids.map(id => `task_ids=${encodeURIComponent(id)}`).join('&')}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error(res.status)
    records.value = records.value.filter(r => !checkedIds.value.has(r.task_id))
    checkedIds.value = new Set()
    if (records.value.length === 0) batchMode.value = false
  } catch (e) {
    alert('刪除失敗：' + e)
  } finally {
    deleting.value = false
  }
}

function handleTileClick(r) {
  if (batchMode.value) {
    toggleCheck(r.task_id)
  } else {
    selected.value = r
  }
}

onMounted(async () => {
  try {
    const res = await fetch(`${API_BASE}/api/history`)
    if (!res.ok) throw new Error(res.status)
    records.value = await res.json()
  } catch (e) {
    error.value = '無法載入歷史紀錄'
  } finally {
    loading.value = false
  }
})

function formatTime(ts) {
  return ts ? ts.replace('T', ' ') : ''
}

function techBadges(r) {
  const badges = []
  const b = (r.backend || '').toLowerCase()
  if (b.includes('ipadapter') || r.style_method === 'ipadapter') badges.push({ label: 'IP-Adapter', cls: 'tech-ip' })
  else if (b.includes('redux') || r.style_method === 'redux') badges.push({ label: 'Redux', cls: 'tech-redux' })
  else if (r.gemini_style_description) badges.push({ label: 'Gemini', cls: 'tech-gemini' })
  if (b.includes('fal')) badges.push({ label: 'fal.ai', cls: 'provider' })
  else if (b.includes('hf')) badges.push({ label: 'HF', cls: 'provider' })
  return badges
}

function clipScore(r) {
  const s = r.evaluation_result?.scores?.clip_similarity ?? null
  return s !== null ? (s * 100).toFixed(1) + '%' : null
}

function clipColor(r) {
  const s = r.evaluation_result?.scores?.clip_similarity ?? null
  if (s === null) return '#bbb'
  if (s >= 0.28) return '#1a7a40'
  if (s >= 0.22) return '#8a6a00'
  return '#a03030'
}

function styleRefUrl(r) {
  if (r.style_reference_image_url) return r.style_reference_image_url
  const p = r.style_reference_image_path || ''
  if (!p) return null
  return `${API_BASE}/${p.replace(/\\/g, '/')}`
}

function styleKbUrl(r) {
  return r.style_params?.reference_image_url || null
}

function styleRefSource(r) {
  if (r.style_reference_source) return r.style_reference_source
  // Fallback for old records: a non-localhost URL means it came from Supabase KB
  const u = r.style_reference_image_url || ''
  if (u) return u.startsWith('http://localhost') ? 'user' : 'supabase'
  if (r.style_reference_image_path && !r.style_reference_image_path.startsWith('http')) return 'user'
  if (r.style_params?.reference_image_url) return 'supabase'
  return null
}

function modelBadge(r) {
  const mt = (r.model_type || '').toLowerCase()
  if (mt === 'flux') return { label: 'FLUX', cls: 'model-flux' }
  if (mt === 'sdxl') return { label: 'SDXL', cls: 'model-sdxl' }
  return null
}
</script>

<template>
  <div class="history-page">
    <header class="history-header">
      <button class="back-btn" @click="router.push('/')">← 返回</button>
      <h1>生成歷史 <span class="count" v-if="records.length">{{ records.length }} 筆</span></h1>
      <div class="header-actions">
        <template v-if="batchMode">
          <button class="action-btn select-all" @click="toggleAll">
            {{ allChecked ? '取消全選' : '全選' }}
          </button>
          <button class="action-btn delete-btn" :disabled="!checkedCount || deleting" @click="deleteSelected">
            {{ deleting ? '刪除中…' : `刪除 (${checkedCount})` }}
          </button>
          <button class="action-btn cancel-btn" @click="toggleBatchMode">取消</button>
        </template>
        <template v-else>
          <button
            :class="['action-btn', 'fav-filter-btn', { active: favoritesOnly }]"
            @click="favoritesOnly = !favoritesOnly"
          >★ 只看收藏</button>
          <button class="action-btn batch-btn" @click="toggleBatchMode">批量管理</button>
        </template>
      </div>
    </header>

    <div v-if="loading" class="state-msg">載入中…</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>
    <div v-else-if="records.length === 0" class="state-msg">尚無歷史紀錄</div>
    <div v-else-if="visibleRecords.length === 0" class="state-msg">還沒有收藏任何設計</div>

    <!-- 縮圖格狀 -->
    <div v-else class="grid">
      <div
        v-for="r in visibleRecords"
        :key="r.task_id"
        :class="['tile', { 'tile-checked': checkedIds.has(r.task_id), 'batch-mode': batchMode }]"
        @click="handleTileClick(r)"
      >
        <!-- 圖片區：生成圖為主，參考圖縮略在右下角 -->
        <div class="tile-img-wrap">
          <img
            v-if="r.generated_image_url"
            :src="r.generated_image_url"
            class="tile-img"
            loading="lazy"
            @error="$event.target.style.display='none'"
          />
          <div v-else class="tile-no-img">無圖</div>

          <!-- 收藏星標：批量模式下不能點，避免跟勾選手勢打架 -->
          <button
            v-if="!batchMode"
            type="button"
            :class="['tile-fav', { active: r.favorited }]"
            :disabled="favoritingIds.has(r.task_id)"
            :title="r.favorited ? '取消收藏' : '收藏這個設計'"
            @click.stop="toggleFavorite(r)"
          >{{ r.favorited ? '★' : '☆' }}</button>

          <!-- 風格參考圖（右下角小圖） -->
          <div v-if="styleRefUrl(r) || styleKbUrl(r)" class="tile-ref-group">
            <img
              :src="styleRefUrl(r) || styleKbUrl(r)"
              class="tile-ref-thumb"
              loading="lazy"
              @error="$event.target.closest('.tile-ref-group').style.display='none'"
            />
            <span v-if="styleRefSource(r)" :class="['ref-src', styleRefSource(r)]">
              {{ styleRefSource(r) === 'user' ? '用戶上傳' : 'Supabase' }}
            </span>
          </div>

          <!-- 批量勾選框 -->
          <div v-if="batchMode" class="tile-checkbox">
            <span :class="['checkbox-icon', { checked: checkedIds.has(r.task_id) }]">
              {{ checkedIds.has(r.task_id) ? '✓' : '' }}
            </span>
          </div>

          <!-- 技術 badge + 模型類型 -->
          <div class="tile-badges">
            <span v-if="modelBadge(r)" :class="['tbadge', modelBadge(r).cls]">{{ modelBadge(r).label }}</span>
            <span v-for="b in techBadges(r)" :key="b.label" :class="['tbadge', b.cls]">{{ b.label }}</span>
          </div>

          <!-- CLIP 分數（僅在圖上顯示） -->
          <div v-if="clipScore(r)" class="tile-clip" :style="{ color: clipColor(r) }">
            CLIP {{ clipScore(r) }}
          </div>
        </div>

        <!-- 資訊區 -->
        <div class="tile-footer">
          <p class="tile-prompt">{{ r.text_prompt || '（無描述）' }}</p>

          <!-- 風格 & 路由 badges -->
          <div class="tile-meta">
            <span v-if="r.style_params?.style_profile_name" class="tile-badge style">{{ r.style_params.style_profile_name }}</span>
            <span v-if="r.routing_decision" class="tile-badge route">{{ r.routing_decision }}</span>
          </div>

          <div class="tile-bottom">
            <span class="tile-time">{{ formatTime(r.timestamp).slice(0, 16) }}</span>
            <span v-if="r.elapsed_seconds" class="tile-elapsed">{{ r.elapsed_seconds }}s</span>
          </div>
          <p v-if="r.gemini_style_description" class="tile-gemini">{{ r.gemini_style_description }}</p>
          <p v-if="r.style_params?.style_summary" class="tile-summary">{{ r.style_params.style_summary }}</p>
        </div>
      </div>
    </div>

    <!-- 詳細面板（點擊後顯示） -->
    <Teleport to="body">
      <div v-if="selected" class="overlay" @click.self="selected = null">
        <div class="panel">
          <button class="close-btn" @click="selected = null">✕</button>

          <div class="panel-images">
            <div class="panel-img-wrap">
              <div class="panel-img-label">生成結果</div>
              <a :href="selected.generated_image_url" target="_blank">
                <img v-if="selected.generated_image_url" :src="selected.generated_image_url" class="panel-img" @error="$event.target.style.display='none'" />
              </a>
            </div>
            <div class="panel-img-wrap" v-if="styleRefUrl(selected) || styleKbUrl(selected)">
              <div class="panel-img-label">
                風格參考圖
                <span v-if="styleRefSource(selected)" :class="['panel-src-tag', styleRefSource(selected)]">
                  {{ styleRefSource(selected) === 'user' ? '用戶上傳' : 'Supabase KB' }}
                </span>
              </div>
              <img :src="styleRefUrl(selected) || styleKbUrl(selected)" class="panel-img" @error="$event.target.style.display='none'" />
            </div>
          </div>

          <div class="panel-body">
            <p class="panel-prompt">{{ selected.text_prompt }}</p>

            <div class="badges">
              <span v-for="b in techBadges(selected)" :key="b.label" :class="['badge', b.cls]">{{ b.label }}</span>
              <span v-if="selected.routing_decision" class="badge route">{{ selected.routing_decision }}</span>
              <span v-if="selected.style_params?.style_profile_name" class="badge style">{{ selected.style_params.style_profile_name }}</span>
            </div>

            <div class="meta-row">
              <span class="time">{{ formatTime(selected.timestamp) }}</span>
              <span v-if="selected.elapsed_seconds" class="time">{{ selected.elapsed_seconds }}s</span>
              <span v-if="clipScore(selected)" class="clip" :style="{ color: clipColor(selected) }">
                CLIP {{ clipScore(selected) }}
              </span>
            </div>

            <div v-if="selected.gemini_style_description" class="info-block gemini">
              <div class="block-label">Gemini 風格分析</div>
              <p>{{ selected.gemini_style_description }}</p>
            </div>

            <div v-if="selected.style_params?.style_summary" class="info-block summary">
              <div class="block-label">風格摘要</div>
              <p>{{ selected.style_params.style_summary }}</p>
            </div>

            <details class="json-details">
              <summary>Generation Params</summary>
              <pre>{{ JSON.stringify(selected.generation_params || {}, null, 2) }}</pre>
            </details>
            <details class="json-details">
              <summary>CLIP Evaluation</summary>
              <pre>{{ JSON.stringify(selected.evaluation_result || {}, null, 2) }}</pre>
            </details>
            <details class="json-details">
              <summary>Style Params</summary>
              <pre>{{ JSON.stringify(selected.style_params || {}, null, 2) }}</pre>
            </details>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.history-page { max-width: 1400px; margin: 0 auto; padding: 1.5rem; font-family: sans-serif; }

.history-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.25rem; }
.history-header h1 { font-size: 1.3rem; margin: 0; }
.count { font-size: 0.85rem; color: #999; font-weight: 400; }
.back-btn { background: none; border: 1px solid #999; border-radius: 6px; padding: 0.3rem 0.8rem; cursor: pointer; font-size: 0.88rem; color: #333; font-weight: 600; }
.back-btn:hover { background: #eee; border-color: #666; }
.header-actions { margin-left: auto; display: flex; gap: 0.5rem; align-items: center; }
.action-btn { font-size: 0.82rem; border-radius: 6px; padding: 0.3rem 0.85rem; cursor: pointer; border: 1px solid transparent; }
.batch-btn  { background: #f5e8d8; color: #5c3d24; border-color: #d4b89a; }
.batch-btn:hover { background: #ead8c0; }
.select-all { background: none; color: #5c3d24; border-color: #d4b89a; }
.select-all:hover { background: #f7f0e8; }
.delete-btn { background: #c0392b; color: #fff; border-color: #a93226; }
.delete-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.delete-btn:not(:disabled):hover { background: #a93226; }
.cancel-btn { background: none; color: #555; border-color: #aaa; font-weight: 600; }
.cancel-btn:hover { background: #f0f0f0; color: #333; }
.fav-filter-btn { background: none; color: #a08050; border-color: #d4b89a; }
.fav-filter-btn:hover { background: #f7f0e8; }
.fav-filter-btn.active { background: #8B5E3C; color: #fff; border-color: #8B5E3C; }

.state-msg { text-align: center; color: #888; padding: 3rem; }
.state-msg.error { color: #c00; }

/* 縮圖格 */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 0.75rem; }

.tile { border: 1px solid #e8ddd0; border-radius: 10px; overflow: hidden; cursor: pointer; background: #fffaf5; transition: box-shadow 0.15s; }
.tile:hover { box-shadow: 0 4px 18px rgba(139,94,60,0.18); border-color: #d4b89a; }

.tile-img-wrap { position: relative; aspect-ratio: 4/3; background: #f5f5f5; overflow: hidden; }
.tile-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.tile-no-img { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; color: #bbb; font-size: 0.78rem; }

/* 風格參考圖：右下角小圖 */
.tile-ref-group { position: absolute; bottom: 6px; right: 6px; width: 60px; display: flex; flex-direction: column; align-items: stretch; }
.tile-ref-thumb { width: 60px; height: 56px; object-fit: cover; border-radius: 5px 5px 0 0; border: 2px solid #fff; border-bottom: none; box-shadow: 0 1px 6px rgba(0,0,0,0.25); display: block; }
.ref-src { text-align: center; font-size: 0.5rem; font-weight: 600; line-height: 1.4; padding: 0.05rem 0; border-radius: 0 0 4px 4px; }
.ref-src.user     { background: #f0c040; color: #3a2200; }
.ref-src.supabase { background: #3ecf8e; color: #00402a; }
.panel-src-tag { font-size: 0.6rem; padding: 0.08rem 0.38rem; border-radius: 3px; margin-left: 0.35rem; font-weight: 600; }
.panel-src-tag.user     { background: rgba(240,192,64,0.9); color: #3a2200; }
.panel-src-tag.supabase { background: rgba(62,207,142,0.9); color: #00402a; }

.tile-badges { position: absolute; top: 5px; left: 5px; display: flex; flex-direction: column; gap: 2px; }
.tbadge { font-size: 0.6rem; padding: 0.08rem 0.38rem; border-radius: 3px; opacity: 0.93; }
.tbadge.model-flux  { background: rgba(30,30,50,0.82); color: #d4c8ff; }
.tbadge.model-sdxl  { background: rgba(20,40,20,0.82); color: #b8e8c0; }
.tbadge.tech-ip     { background: #dff0e8; color: #1a6644; }
.tbadge.tech-redux  { background: #e8eeff; color: #2a3f99; }
.tbadge.tech-gemini { background: #fff3e0; color: #8a5500; }
.tbadge.provider    { background: rgba(255,255,255,0.88); color: #666; }

.tile-clip { position: absolute; bottom: 6px; left: 6px; font-size: 0.62rem; font-weight: 700; background: rgba(255,255,255,0.88); border-radius: 3px; padding: 0.06rem 0.35rem; }
.tile-fav {
  position: absolute; top: 6px; right: 6px; z-index: 2;
  width: 26px; height: 26px; display: flex; align-items: center; justify-content: center;
  border: none; border-radius: 50%; cursor: pointer;
  background: rgba(255,255,255,0.85); color: #b8a888; font-size: 1.05rem; line-height: 1;
  box-shadow: 0 1px 4px rgba(0,0,0,0.2);
}
.tile-fav:hover { background: #fff; }
.tile-fav.active { color: #d4a017; }
.tile-fav:disabled { opacity: 0.5; cursor: not-allowed; }
.tile-checkbox { position: absolute; top: 6px; right: 6px; z-index: 2; }
.checkbox-icon { display: flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; border: 2px solid #fff; background: rgba(255,255,255,0.7); font-size: 0.7rem; font-weight: 700; color: #fff; box-shadow: 0 1px 4px rgba(0,0,0,0.2); }
.checkbox-icon.checked { background: #8B5E3C; border-color: #8B5E3C; }
.tile-checked { border-color: #8B5E3C; box-shadow: 0 0 0 2px #d4b89a; }
.batch-mode { cursor: default; }

.tile-footer { padding: 0.55rem 0.7rem; display: flex; flex-direction: column; gap: 0.32rem; }
.tile-prompt { font-size: 0.78rem; color: #222; margin: 0; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

.tile-meta { display: flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; }
.tile-badge { font-size: 0.64rem; padding: 0.12rem 0.45rem; border-radius: 999px; white-space: nowrap; }
.tile-badge.tech-ip     { background: #dff0e8; color: #1a6644; }
.tile-badge.tech-redux  { background: #e8eeff; color: #2a3f99; }
.tile-badge.tech-gemini { background: #fff3e0; color: #8a5500; }
.tile-badge.provider    { background: #f5e8d8; color: #5c3d24; }
.tile-badge.style       { background: #fff0d8; color: #8a5a00; }
.tile-badge.route       { background: #f0f0f0; color: #666; }
.tile-badge.clip-badge  { background: #f5f5f5; font-weight: 700; }

.tile-bottom { display: flex; gap: 0.75rem; }
.tile-time    { font-size: 0.65rem; color: #aaa; }
.tile-elapsed { font-size: 0.65rem; color: #bbb; }
.tile-gemini  { font-size: 0.7rem; color: #7a5530; margin: 0; line-height: 1.4; border-left: 2px solid #d4b89a; padding-left: 0.4rem;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.tile-summary { font-size: 0.7rem; color: #3a7a5a; margin: 0; line-height: 1.4; border-left: 2px solid #81c995; padding-left: 0.4rem;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

/* 詳細 overlay */
.overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 1rem; }

.panel { background: #fff; border-radius: 14px; max-width: 820px; width: 100%; max-height: 90vh; overflow-y: auto; position: relative; }

.close-btn { position: absolute; top: 0.75rem; right: 0.9rem; background: none; border: none; font-size: 1.1rem; cursor: pointer; color: #888; z-index: 1; }
.close-btn:hover { color: #333; }

.panel-images { display: flex; border-bottom: 1px solid #f0e8d8; }
.panel-img-wrap { flex: 1; position: relative; }
.panel-img-wrap + .panel-img-wrap { border-left: 1px solid #f0e8d8; }
.panel-img-label { position: absolute; top: 6px; left: 8px; font-size: 0.65rem; background: rgba(0,0,0,0.5); color: #fff; padding: 0.1rem 0.4rem; border-radius: 4px; z-index: 1; }
.panel-img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; }

.panel-body { padding: 1rem 1.25rem; display: flex; flex-direction: column; gap: 0.5rem; }
.panel-prompt { font-size: 0.92rem; color: #222; margin: 0; line-height: 1.5; padding-right: 1.5rem; }

.badges { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.badge { font-size: 0.68rem; padding: 0.12rem 0.5rem; border-radius: 999px; }
.badge.tech-ip     { background: #dff0e8; color: #1a6644; }
.badge.tech-redux  { background: #e8eeff; color: #2a3f99; }
.badge.tech-gemini { background: #fff3e0; color: #8a5500; }
.badge.provider    { background: #f5e8d8; color: #5c3d24; }
.badge.route       { background: #f0f0f0; color: #666; }
.badge.style       { background: #fff0d8; color: #8a5a00; }

.meta-row { display: flex; gap: 1rem; align-items: center; }
.time { font-size: 0.72rem; color: #999; }
.clip { font-size: 0.78rem; font-weight: 700; margin-left: auto; }

.info-block { border-left: 3px solid #ccc; border-radius: 0 6px 6px 0; padding: 0.45rem 0.7rem; }
.info-block.gemini  { background: #fdf6ee; border-color: #d4b89a; }
.info-block.summary { background: #f6fbf8; border-color: #81c995; }
.info-block p { font-size: 0.8rem; color: #444; margin: 0; line-height: 1.55; }
.block-label { font-size: 0.63rem; font-weight: 700; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.2rem; }

.json-details { border: 1px solid #e8ddd0; border-radius: 6px; overflow: hidden; }
.json-details summary { padding: 0.4rem 0.75rem; cursor: pointer; font-size: 0.75rem; color: #8B5E3C; font-weight: 600; background: #fdf6ee; user-select: none; }
.json-details summary:hover { background: #f7f0e8; }
.json-details pre { background: #2c1810; color: #e8d4b8; font-size: 0.7rem; margin: 0; padding: 0.6rem 0.9rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all; }
</style>
