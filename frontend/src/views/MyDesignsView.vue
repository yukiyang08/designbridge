<script setup>
/**
 * 我的設計 — 目前登入者的設計（即歷史紀錄）。一張卡片 = 一個設計（project），
 * 底下分空間（客廳、主臥…），每個空間有多張渲染圖（每次生成／換風格／微調各一張）。
 * 資料來自 /api/history（Supabase designs 表，依 user_id 隔離），前端依 project_id 分組。
 */
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { authFetch, jsonFetch } from '@/config/api'
import { cleanDescription } from '@/utils/text'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { useAuth } from '@/composables/useAuth'
import AppNav from '@/components/shell/AppNav.vue'
import sceneBg from '@/assets/figma/room-bg.png'

const router = useRouter()
const { user } = useAuth()
const badImg = reactive({})   // 載入失敗的圖片網址（雲端上傳失敗或網址過期），改顯示「無圖」
const imgOk = (u) => !!u && !badImg[u]
const markBad = (u) => { if (u) badImg[u] = true }
const { startFlow, extraPrompt, selectedStyle, noStyleReference, restoreProject } = useDesignFlow()

const records = ref([])
const loading = ref(true)
const error = ref('')
const deleting = ref(false)

onMounted(async () => {
  try {
    const res = await authFetch('/api/history')
    if (!res.ok) throw new Error(res.status)
    records.value = await res.json()
  } catch {
    error.value = '無法載入設計'
  } finally {
    loading.value = false
  }
})

// ── 分組：設計 → 空間 → 渲染圖（records 已是新到舊）──
const projects = computed(() => {
  const map = new Map()
  for (const r of records.value) {
    const pid = r.project_id || r.task_id
    if (!map.has(pid)) map.set(pid, [])
    map.get(pid).push(r)
  }
  return [...map].map(([id, renders]) => {
    const spaces = new Map()
    for (const r of renders) {
      const sid = r.space_id || 'main'
      if (!spaces.has(sid)) spaces.set(sid, { id: sid, name: r.space_name || '主要空間', renders: [] })
      spaces.get(sid).renders.push(r)
    }
    const spaceList = [...spaces.values()]
    const cover = renders[0]
    // 整層設計才知道「總共幾間」；單空間／照片設計沒有這個依據
    const totalRooms = cover.cad_summary?.rooms?.length || 0
    const quoted = spaceList.map(s => quoteOf(s.renders[0])).filter(Boolean)
    return {
      id, renders, cover,
      isOwner: cover.role !== 'editor',   // editor = 被邀請共編
      title: renders[renders.length - 1].title || '未命名設計',
      spaces: spaceList,
      totalRooms,
      doneRooms: spaceList.length,
      area: cover.cad_summary?.total_m2 || 0,
      quotedCount: quoted.length,
      budget: quoted.reduce((sum, q) => sum + quotationTotal(q), 0),
    }
  })
})

// 每個空間取最新一版已有的估價（存過的或剛在詳情按出來的）
const quoteOf = r => quotations[r.task_id]?.data || r.quotation || null

function projectStatus(p) {
  if (!p.totalRooms) return null
  return p.doneRooms >= p.totalRooms
    ? { text: '✓ 已完成', cls: 'done' }
    : { text: `進行中 ${p.doneRooms} / ${p.totalRooms} 間`, cls: 'wip' }
}

function relTime(ts) {
  if (!ts) return ''
  const days = Math.floor((Date.now() - new Date(ts).getTime()) / 86400000)
  if (days < 1) return '今天'
  if (days < 30) return `${days} 天前`
  return formatTime(ts).slice(0, 10)
}

// ── 詳情 ──
const openId = ref(null)
const activeSpaceId = ref(null)
const activeTaskId = ref(null)
const imgKind = ref('render')   // render | plan | photo

const openProject = computed(() => projects.value.find(p => p.id === openId.value) || null)
const activeSpace = computed(() =>
  openProject.value?.spaces.find(s => s.id === activeSpaceId.value) || openProject.value?.spaces[0] || null)
const activeRender = computed(() =>
  activeSpace.value?.renders.find(r => r.task_id === activeTaskId.value) || activeSpace.value?.renders[0] || null)

const imageKinds = computed(() => {
  const r = activeRender.value
  if (!r) return []
  return [
    { key: 'render', label: '渲染', url: r.generated_image_url },
    { key: 'cad', label: 'CAD', url: r.cad_svg_url },
    { key: 'plan', label: '配置', url: r.floor_plan_url },
    { key: 'photo', label: '原照', url: r.source_photo_url },
  ].filter(k => k.url)
})
const mainImage = computed(() => (imageKinds.value.find(k => k.key === imgKind.value) || imageKinds.value[0])?.url || '')

// 尺寸資訊：整層（CAD 才有）與目前這個空間
const fmt = n => (Math.round(n * 100) / 100).toString()
const dimLines = computed(() => {
  const r = activeRender.value
  if (!r) return []
  const out = []
  const cad = r.cad_summary
  if (cad?.bounding_w_m) {
    out.push(`整層：${fmt(cad.bounding_w_m)} × ${fmt(cad.bounding_d_m)} m，共 ${fmt(cad.total_m2)} m²`)
  }
  const room = cad?.rooms?.find(x => x.id === r.space_id)
  if (room) out.push(`${r.space_name}：${fmt(room.w)} × ${fmt(room.h)} m，${fmt(room.area_m2)} m²`)
  else if (r.space_dims) {
    const { w, d } = r.space_dims
    out.push(`${r.space_name}：${fmt(w)} × ${fmt(d)} m，${fmt(w * d)} m²`)
  }
  return out
})

function openDetail(p) {
  openId.value = p.id
  activeSpaceId.value = p.spaces[0].id
  activeTaskId.value = null
  imgKind.value = 'render'
}
function pickSpace(s) { activeSpaceId.value = s.id; activeTaskId.value = null; imgKind.value = 'render' }
function closeDetail() { openId.value = null; zoomed.value = false }
const zoomed = ref(false)

// ── 刪除 ──
async function removeTasks(ids) {
  deleting.value = true
  try {
    const qs = ids.map(id => `task_ids=${encodeURIComponent(id)}`).join('&')
    const res = await authFetch(`/api/history?${qs}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(res.status)
    const gone = new Set(ids)
    records.value = records.value.filter(r => !gone.has(r.task_id))
    return true
  } catch {
    error.value = '刪除失敗，請稍後再試'
    return false
  } finally {
    deleting.value = false
  }
}

async function deleteProject(p) {
  if (!confirm(`確定刪除「${p.title}」整個設計（${p.renders.length} 張圖）？刪除後無法復原。`)) return
  if (await removeTasks(p.renders.map(r => r.task_id)) && openId.value === p.id) closeDetail()
}

async function deleteRender(r) {
  if (!confirm('確定刪除這張圖？刪除後無法復原。')) return
  if (!(await removeTasks([r.task_id]))) return
  activeTaskId.value = null
  if (!openProject.value) closeDetail()
}

function formatTime(ts) {
  return ts ? ts.replace('T', ' ').slice(0, 16) : ''
}

function styleLabel(r) {
  return r?.style_params?.style_profile_name || null
}

function styleDescription(r) {
  return cleanDescription(r?.gemini_style_description || r?.style_params?.style_summary || '')
}

// ── 家具預算：點了才打 /api/quotation（要辨識畫面家具，約 30 秒）；存過的直接顯示 ──
const quotations = reactive({})   // task_id -> { loading, error, data }

function qState(r) {
  return quotations[r.task_id] ||= { loading: false, error: '', data: r.quotation || null }
}

async function loadQuotation(r) {
  const st = qState(r)
  if (st.data || st.loading) return
  st.loading = true
  st.error = ''
  try {
    const res = await jsonFetch('/api/quotation', {
      image_path: r.generated_image_path,
      structured_requirement: r.structured_requirement || null,
      selected_furniture: [],
      task_id: r.task_id,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    st.data = await res.json()
  } catch {
    st.error = '估價失敗，請稍後再試'
  } finally {
    st.loading = false
  }
}

function quotationTotal(data) {
  return (data?.furniture_list || []).reduce((sum, item) => sum + (item.candidates?.[0]?.price ?? 0), 0)
}

// ── 分享與共編：唯讀連結（不用登入）、邀請連結（登入後成為共編者，可輪流編輯、不能刪除）──
const shareKinds = [
  { key: 'invite', token: 'invite_token', path: 'invite', icon: '👥', title: '邀請別人一起編輯',
    hint: '對方登入後點連結就能加入，可以一起修改與生成，但不能刪除設計。' },
  { key: 'share', token: 'share_token', path: 's', icon: '👁', title: '公開連結（只能看）',
    hint: '任何人有連結都能查看，不用登入，也不能修改。' },
]
const shareOpen = ref(false)
const shareProject = ref(null)   // 卡片與詳情頁都能開分享，所以不綁 openProject
const sharing = ref(null)
const shareBusy = ref(false)
const shareError = ref('')
const copied = ref('')

async function shareRequest(call) {
  shareBusy.value = true
  shareError.value = ''
  try {
    const res = await call()
    if (!res.ok) throw new Error(res.status)
    sharing.value = await res.json()
  } catch {
    shareError.value = '操作失敗，請稍後再試'
  } finally {
    shareBusy.value = false
  }
}
const sharingUrl = () => `/api/projects/${shareProject.value.id}/sharing`
function openShare(p) {
  shareProject.value = p
  shareOpen.value = true
  sharing.value = null
  shareRequest(() => authFetch(sharingUrl()))
}
function stopShare(k) {
  if (confirm(`停用後，已經傳出去的連結會立刻失效。確定停用「${k.title}」？`)) toggleShare(k, false)
}
const toggleShare = (k, on) => shareRequest(() => jsonFetch(sharingUrl(), { [k.key]: on }, 'PUT'))
const linkOf = k => new URL(router.resolve(`/${k.path}/${sharing.value[k.token]}`).href, location.origin).href
async function copyLink(k) {
  try {
    await navigator.clipboard.writeText(linkOf(k))
    copied.value = k.key
    setTimeout(() => { copied.value = '' }, 1500)
  } catch {
    shareError.value = '無法自動複製，請手動選取連結'
  }
}
async function removeMember(m) {
  if (!confirm(`確定移除 ${m.email || '這位成員'}？`)) return
  await authFetch(`/api/projects/${shareProject.value.id}/members/${m.user_id}`, { method: 'DELETE' })
  shareRequest(() => authFetch(sharingUrl()))
}
async function leaveProject(p) {
  if (!confirm(`確定退出「${p.title}」？退出後需要重新取得邀請才能再編輯。`)) return
  const res = await authFetch(`/api/projects/${p.id}/members/${user.value.id}`, { method: 'DELETE' })
  if (!res.ok) { error.value = '退出失敗，請稍後再試'; return }
  records.value = records.value.filter(r => r.project_id !== p.id)
  closeDetail()
}

// ── 繼續編輯：整層設計從雲端還原平面圖與每間房的結果，落在整層總覽 ──
const restoring = ref(false)
const isCadProject = (p) => !!p?.cover?.cad_summary
async function continueEditing(p) {
  restoring.value = true
  error.value = ''
  try {
    await restoreProject(p.id)
    router.push('/studio')
  } catch (e) {
    error.value = e.message || '無法載入這個設計'
  } finally {
    restoring.value = false
  }
}

// ── 用同樣描述再設計一次：輕量版重用（文字描述＋風格庫風格）──
function reuseDesign(r) {
  startFlow('skip')
  extraPrompt.value = r.text_prompt || ''
  const styleId = r.style_params?.style_profile_id
  if (styleId) {
    selectedStyle.value = styleId
    noStyleReference.value = false
  }
  router.push('/studio')
}
</script>

<template>
  <div class="db-scene" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />
    <div class="db-card designs">
      <header class="head">
        <h1 class="title">我的設計 <span v-if="projects.length" class="count">{{ projects.length }} 個</span></h1>
        <button class="db-btn db-btn--sm" @click="router.push('/start')">＋ 新的設計</button>
      </header>

      <p v-if="error" class="db-error err">{{ error }}</p>

      <div v-if="loading" class="grid" aria-busy="true">
        <div v-for="n in 6" :key="n" class="card skeleton"></div>
      </div>
      <div v-else-if="projects.length === 0 && !error" class="empty-state">
        <p>還沒有任何設計</p>
        <p class="empty-hint">每次生成的設計都會自動存在這裡。</p>
        <button class="db-btn" @click="router.push('/start')">開始新的設計</button>
      </div>

      <div v-else class="grid">
        <article v-for="p in projects" :key="p.id" class="card" @click="openDetail(p)">
          <div :class="['card-img-wrap', { mosaic: p.spaces.length > 1 }]">
            <div class="main-cell">
              <img v-if="imgOk(p.cover.generated_image_url)" :src="p.cover.generated_image_url" alt="" class="card-img" loading="lazy" @error="markBad(p.cover.generated_image_url)" />
              <div v-else class="card-no-img">無圖</div>
            </div>
            <div v-if="p.spaces.length > 1" class="side-col">
              <div v-for="(s, i) in p.spaces.slice(1, 3)" :key="s.id" class="side-cell" :title="s.name">
                <img v-if="imgOk(s.renders[0].generated_image_url)" :src="s.renders[0].generated_image_url" alt="" class="card-img" loading="lazy" @error="markBad(s.renders[0].generated_image_url)" />
                <span v-if="i === 1 && p.spaces.length > 3" class="more">+{{ p.spaces.length - 3 }}</span>
              </div>
            </div>
            <span v-if="projectStatus(p)" :class="['status', projectStatus(p).cls]">{{ projectStatus(p).text }}</span>
            <span v-if="!p.isOwner" class="shared-tag">共編</span>
            <button
              v-if="p.isOwner" type="button" class="del-btn" title="刪除整個設計" :disabled="deleting"
              @click.stop="deleteProject(p)"
            >✕</button>
          </div>
          <div class="card-body">
            <p class="card-title">{{ p.title }}</p>
            <p class="card-meta">
              {{ [p.spaces.length > 1 && `${p.spaces.length} 個空間`, p.area && `${fmt(p.area)} m²`, styleLabel(p.cover)].filter(Boolean).join(' · ') }}
            </p>
            <p v-if="p.quotedCount" class="budget">NT$ {{ p.budget.toLocaleString() }}</p>
            <div class="card-foot">
              <span class="card-time">{{ relTime(p.cover.timestamp) }}</span>
              <div class="card-actions">
                <button type="button" class="icon-btn" title="查看詳情" aria-label="查看詳情" @click.stop="openDetail(p)">
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
                <button
                  v-if="p.isOwner" type="button" class="icon-btn" title="分享與共編" aria-label="分享與共編"
                  @click.stop="openShare(p)"
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" />
                    <path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4" />
                  </svg>
                </button>
                <button
                  v-if="isCadProject(p)" type="button" class="icon-btn primary" title="繼續編輯" aria-label="繼續編輯"
                  :disabled="restoring" @click.stop="continueEditing(p)"
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>
    </div>

    <!-- 詳情 -->
    <div v-if="openProject" class="overlay" @click.self="closeDetail">
      <div class="panel" role="dialog" aria-modal="true">
        <header class="panel-head">
          <h2>{{ openProject.title }}</h2>
          <button type="button" class="x" aria-label="關閉" @click="closeDetail">✕</button>
        </header>

        <div v-if="openProject.spaces.length > 1" class="tabs">
          <button
            v-for="s in openProject.spaces" :key="s.id" type="button"
            :class="['tab', { on: s.id === activeSpace?.id }]" @click="pickSpace(s)"
          >{{ s.name }}</button>
        </div>

        <div v-if="activeRender" class="panel-body">
          <div class="viewer">
            <div class="stage">
              <img v-if="imgOk(mainImage)" :src="mainImage" @error="markBad(mainImage)" alt="" :class="['main-img', { cover: mainImage === activeRender.generated_image_url }]" title="點擊放大" @click="zoomed = true" />
              <div v-else class="card-no-img">無圖</div>
              <div v-if="imageKinds.length > 1" class="kinds">
                <button
                  v-for="k in imageKinds" :key="k.key" type="button"
                  :class="['kind', { on: k.url === mainImage }]" @click="imgKind = k.key"
                >{{ k.label }}</button>
              </div>
            </div>
            <div v-if="activeSpace.renders.length > 1" class="versions">
              <button
                v-for="(r, i) in activeSpace.renders" :key="r.task_id" type="button"
                :class="['ver', { on: r.task_id === activeRender.task_id }]"
                :title="formatTime(r.timestamp)" @click="activeTaskId = r.task_id; imgKind = 'render'"
              >
                <img v-if="imgOk(r.generated_image_url)" :src="r.generated_image_url" alt="" @error="markBad(r.generated_image_url)" />
                <span>{{ i === 0 ? '最新' : formatTime(r.timestamp).slice(5) }}</span>
              </button>
            </div>
          </div>

          <div class="info">
            <p class="prompt">{{ activeRender.text_prompt || '（無描述）' }}</p>
            <p class="meta">
              {{ [activeSpace.name, dimLines.at(-1)?.replace(/^[^：]*：/, ''), styleLabel(activeRender)].filter(Boolean).join(' · ') }}
              <span class="card-time">{{ formatTime(activeRender.timestamp) }}</span>
            </p>

            <div class="actions">
              <button
                v-if="isCadProject(openProject)" type="button" class="db-btn db-btn--sm"
                :disabled="restoring" @click="continueEditing(openProject)"
              >{{ restoring ? '載入中…' : '繼續編輯' }}</button>
              <button type="button" class="db-btn db-btn--ghost db-btn--sm" @click="reuseDesign(activeRender)">再設計一次</button>
              <button v-if="openProject.isOwner" type="button" class="db-btn db-btn--ghost db-btn--sm" @click="openShare(openProject)">分享</button>
              <button v-if="openProject.isOwner" type="button" class="link-btn" :disabled="deleting" @click="deleteRender(activeRender)">刪除這張</button>
              <button v-else type="button" class="link-btn" @click="leaveProject(openProject)">退出共編</button>
            </div>

            <div class="quotation">
              <button
                v-if="!qState(activeRender).data && !qState(activeRender).loading" type="button"
                class="db-btn db-btn--ghost db-btn--sm" @click="loadQuotation(activeRender)"
              >查看家具預算</button>
              <p v-if="qState(activeRender).loading" class="q-hint" role="status">正在辨識畫面中的家具…約需 30 秒</p>
              <p v-else-if="qState(activeRender).error" class="db-error">{{ qState(activeRender).error }}</p>
              <details v-else-if="qState(activeRender).data" class="q-box">
                <summary>
                  <span>家具預算</span>
                  <strong>NT$ {{ quotationTotal(qState(activeRender).data).toLocaleString() }}</strong>
                </summary>
                <ul class="q-list">
                  <li v-for="(item, idx) in qState(activeRender).data.furniture_list" :key="idx" class="q-item">
                    <img
                      v-if="item.candidates?.[0]?.product_image_url"
                      :src="item.candidates[0].product_image_url" :alt="item.candidates[0].name" class="q-item-img"
                    />
                    <span class="q-item-name">{{ item.candidates?.[0]?.name || item.detected_name }}</span>
                    <span class="q-item-price">NT$ {{ (item.candidates?.[0]?.price ?? 0).toLocaleString() }}</span>
                  </li>
                </ul>
              </details>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 分享與共編（只有擁有者） -->
    <div v-if="shareOpen" class="overlay" @click.self="shareOpen = false">
      <div class="panel share-panel" role="dialog" aria-modal="true">
        <header class="panel-head">
          <h2>分享「{{ shareProject?.title }}」</h2>
          <button type="button" class="x" aria-label="關閉" @click="shareOpen = false">✕</button>
        </header>
        <p v-if="shareError" class="db-error">{{ shareError }}</p>
        <div v-if="sharing" class="share-body">
          <section v-for="k in shareKinds" :key="k.key" class="share-card">
            <div class="share-head">
              <span class="share-ico" aria-hidden="true">{{ k.icon }}</span>
              <div>
                <strong>{{ k.title }}</strong>
                <p>{{ k.hint }}</p>
              </div>
            </div>
            <button
              v-if="!sharing[k.token]" type="button" class="db-btn db-btn--sm share-create"
              :disabled="shareBusy" @click="toggleShare(k, true)"
            >建立連結</button>
            <template v-else>
              <div class="share-link">
                <input readonly :value="linkOf(k)" aria-label="連結" @focus="$event.target.select()" />
                <button type="button" class="db-btn db-btn--sm" @click="copyLink(k)">{{ copied === k.key ? '✓ 已複製' : '複製連結' }}</button>
              </div>
              <button type="button" class="link-btn share-stop" :disabled="shareBusy" @click="stopShare(k)">停用這個連結</button>
            </template>
          </section>

          <section v-if="sharing.invite_token" class="share-card">
            <strong>已加入的共編者（{{ sharing.members.length }}）</strong>
            <p v-if="!sharing.members.length" class="share-empty">還沒有人加入，把上面的邀請連結傳給對方吧。</p>
            <ul v-else class="members">
              <li v-for="m in sharing.members" :key="m.user_id">
                <span class="avatar" aria-hidden="true">{{ (m.email || '?')[0].toUpperCase() }}</span>
                <span class="member-name">{{ m.email || m.user_id.slice(0, 8) }}</span>
                <button type="button" class="link-btn" :disabled="shareBusy" @click="removeMember(m)">移除</button>
              </li>
            </ul>
          </section>
        </div>
        <p v-else-if="!shareError" class="q-hint" aria-busy="true">載入中…</p>
      </div>
    </div>

    <div v-if="zoomed && mainImage" class="lightbox" @click="zoomed = false">
      <img :src="mainImage" alt="" />
    </div>
  </div>
</template>

<style scoped>
.designs { margin: 1.25rem auto 3rem; padding: 1.75rem 1.5rem 3rem; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1.5rem; }
.title {
  display: flex; align-items: center; gap: 0.6rem; margin: 0;
  font-family: var(--db-font-display); font-style: italic; font-weight: 500;
  font-size: 1.6rem; color: var(--db-text);
}
.count { font-size: 0.85rem; color: var(--db-text-soft); font-style: normal; }
.err { margin: 0 0 1rem; }
.shared-tag {
  position: absolute; top: 10px; left: 10px; padding: 0.15rem 0.6rem; border-radius: var(--db-radius-pill);
  background: rgba(255, 255, 255, 0.92); font-size: 0.75rem; color: var(--db-text);
}
.share-panel { width: min(520px, 100%); }
.share-body { display: flex; flex-direction: column; gap: 0.9rem; }
.share-card { display: flex; flex-direction: column; gap: 0.7rem; padding: 1rem 1.1rem; border: 1px solid #ececec; border-radius: var(--db-radius-chip); background: #fff; }
.share-head { display: flex; gap: 0.8rem; align-items: flex-start; }
.share-head p { margin: 0.2rem 0 0; font-size: 0.85rem; line-height: 1.5; color: var(--db-text-soft); }
.share-ico { display: grid; place-items: center; flex: 0 0 40px; height: 40px; border-radius: 50%; background: var(--db-chip-soft); font-size: 1.15rem; }
.share-create { align-self: flex-start; }
.share-link { display: flex; gap: 0.5rem; }
.share-link input { flex: 1; min-width: 0; padding: 0.5rem 0.7rem; border: 1px solid #d8d4cb; border-radius: 8px; background: var(--db-chip-soft); font-size: 0.85rem; }
.share-stop { align-self: flex-start; padding: 0; }
.share-empty { margin: 0; font-size: 0.85rem; color: var(--db-text-soft); }
.members { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.members li { display: flex; align-items: center; gap: 0.6rem; font-size: 0.9rem; }
.member-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.avatar { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; background: var(--db-accent); color: var(--db-on-accent); font-size: 0.85rem; flex-shrink: 0; }

.empty-state { text-align: center; color: var(--db-text-soft); padding: 4rem 0; }
.empty-hint { font-size: 0.88rem; color: var(--db-placeholder); margin: 0 0 1rem; }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(380px, 100%), 1fr)); gap: 1.25rem; }
.card {
  background: #fff; border: 1px solid #ececec; border-radius: var(--db-radius-chip);
  overflow: hidden; cursor: pointer;
  transition: transform 0.16s, box-shadow 0.16s, border-color 0.16s;
}
.card:hover { transform: translateY(-3px); box-shadow: var(--db-shadow-soft); border-color: var(--db-accent); }
.card.skeleton {
  aspect-ratio: 4 / 3.4; cursor: default;
  background: linear-gradient(90deg, #f1efea, #f8f6f2, #f1efea); background-size: 200% 100%;
  animation: sh 1.2s infinite;
}
@keyframes sh { to { background-position: -200% 0; } }

.card-img-wrap { position: relative; aspect-ratio: 4 / 3; background: var(--db-chip-soft); display: flex; gap: 2px; }
.main-cell { flex: 1 1 0; min-width: 0; }
.side-col { flex: 0 0 32%; display: flex; flex-direction: column; gap: 2px; }
.side-cell { position: relative; flex: 1 1 0; min-height: 0; background: var(--db-chip-soft); }
.more {
  position: absolute; inset: 0; display: grid; place-items: center;
  background: rgba(0, 0, 0, 0.45); color: #fff; font-size: 1rem;
}
.card-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card-no-img { display: grid; place-items: center; width: 100%; height: 100%; color: var(--db-placeholder); }
.status {
  position: absolute; left: 10px; bottom: 10px; padding: 0.2rem 0.65rem;
  border-radius: var(--db-radius-pill); color: #fff; font-size: 0.78rem;
}
.status.done { background: rgba(46, 125, 80, 0.9); }
.status.wip { background: rgba(190, 120, 20, 0.9); }
.budget { margin: 0.2rem 0 0; font-size: 0.95rem; font-weight: 600; color: var(--db-text); font-variant-numeric: tabular-nums; }
.card-actions { display: flex; gap: 0.5rem; }
.icon-btn {
  display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid #d8d4cb; border-radius: 50%;
  background: #fff; color: var(--db-text); cursor: pointer; transition: transform 0.16s;
}
.icon-btn.primary { border-color: var(--db-accent); background: var(--db-accent); color: var(--db-on-accent); }
.icon-btn:hover:not(:disabled) { transform: scale(1.08); }
.icon-btn:disabled { opacity: 0.5; cursor: wait; }
.card-foot { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-top: 0.2rem; }
.del-btn {
  position: absolute; top: 10px; right: 10px; width: 30px; height: 30px; border: 0; border-radius: 50%;
  background: rgba(255, 255, 255, 0.9); color: var(--db-text); cursor: pointer; opacity: 0;
  transition: opacity 0.16s;
}
.card:hover .del-btn, .del-btn:focus-visible { opacity: 1; }
@media (hover: none) { .del-btn { opacity: 1; } }
.del-btn:hover { background: #fff; color: #c0392b; }
.del-btn:disabled { cursor: not-allowed; }

.card-body { padding: 0.9rem 1.1rem 1.1rem; display: flex; flex-direction: column; gap: 0.3rem; }
.card-title { margin: 0; font-size: 1rem; color: var(--db-text); line-height: 1.4; }
.card-meta { margin: 0; font-size: 0.82rem; color: var(--db-text-soft); }
.card-time { font-size: 0.75rem; color: var(--db-placeholder); }

.overlay {
  position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 1.5rem;
  background: rgba(0, 0, 0, 0.55);
}
.panel {
  width: min(1100px, 100%); max-height: 100%; overflow: auto;
  background: var(--db-card); border-radius: var(--db-radius-card); box-shadow: var(--db-shadow-card);
  padding: 1.25rem 1.5rem 1.75rem;
}
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.9rem; }
.panel-head h2 {
  margin: 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500;
  font-size: 1.4rem; color: var(--db-text);
}
.x { border: 0; background: none; font-size: 1.1rem; cursor: pointer; color: var(--db-text-soft); }

.tabs { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
.tab {
  padding: 0.35rem 1rem; border: 1px solid #d8d4cb; border-radius: var(--db-radius-pill);
  background: #fff; color: var(--db-text); font-size: 0.9rem; cursor: pointer;
}
.tab.on { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent); }

.panel-body { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 1.5rem; }
.viewer { display: flex; flex-direction: column; gap: 0.7rem; min-width: 0; align-self: start; position: sticky; top: 0; }
.stage {
  position: relative; aspect-ratio: 4 / 3; max-height: 70vh; width: 100%;
  border-radius: var(--db-radius-chip); background: #fff; border: 1px solid #ececec; overflow: hidden;
}
.main-img { width: 100%; height: 100%; object-fit: contain; display: block; cursor: zoom-in; }
.main-img.cover { object-fit: cover; }
.kinds { position: absolute; left: 10px; top: 10px; display: flex; gap: 2px; padding: 3px; border-radius: var(--db-radius-pill); background: rgba(255, 255, 255, 0.92); box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15); }
.versions { display: flex; gap: 0.5rem; overflow-x: auto; padding-bottom: 2px; }
.kind {
  padding: 0.2rem 0.75rem; border: 0; border-radius: var(--db-radius-pill);
  background: none; font-size: 0.8rem; cursor: pointer; color: var(--db-text);
}
.kind.on { background: var(--db-accent); color: var(--db-on-accent); }
.lightbox {
  position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 1rem;
  background: rgba(0, 0, 0, 0.85); cursor: zoom-out;
}
.lightbox img { max-width: 100%; max-height: 100%; object-fit: contain; background: #fff; }
.ver { flex: 0 0 104px; padding: 0; border: 2px solid transparent; border-radius: 8px; background: none; cursor: pointer; text-align: center; }
.ver.on { border-color: var(--db-accent); }
.ver img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 6px; display: block; }
.ver span { font-size: 0.7rem; color: var(--db-text-soft); }

.info { display: flex; flex-direction: column; gap: 0.6rem; min-width: 0; }
.prompt { margin: 0; font-size: 0.98rem; line-height: 1.6; color: var(--db-text); }
.style-tag {
  align-self: flex-start; padding: 0.15rem 0.7rem; border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft); font-size: 0.8rem;
}
.desc { margin: 0; font-size: 0.85rem; line-height: 1.7; color: var(--db-text-soft); }
.dims { margin: 0; padding: 0.6rem 0.9rem; list-style: none; border-radius: 8px; background: var(--db-chip-soft); font-size: 0.85rem; color: var(--db-text); display: flex; flex-direction: column; gap: 0.25rem; }
.actions { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-top: 0.4rem; }

.q-hint { margin: 0; font-size: 0.85rem; color: var(--db-text-soft); }
.q-list { list-style: none; margin: 0 0 0.6rem; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.q-item { display: flex; align-items: center; gap: 0.6rem; }
.q-item-img { width: 36px; height: 36px; object-fit: contain; border-radius: 6px; background: var(--db-chip-soft); flex-shrink: 0; }
.q-item-name {
  flex: 1; min-width: 0; font-size: 0.85rem; color: var(--db-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.q-item-price { font-size: 0.85rem; color: var(--db-text); font-variant-numeric: tabular-nums; }
.meta { margin: 0; font-size: 0.85rem; color: var(--db-text-soft); display: flex; flex-wrap: wrap; gap: 0.2rem 0.75rem; }
.link-btn { border: 0; background: none; padding: 0 0.4rem; font-size: 0.82rem; color: var(--db-text-soft); cursor: pointer; text-decoration: underline; }
.link-btn:hover { color: #c0392b; }
.q-box { border-top: 1px dashed #e8e6e1; padding-top: 0.6rem; }
.q-box summary {
  display: flex; justify-content: space-between; align-items: center; cursor: pointer;
  font-size: 0.92rem; color: var(--db-text); list-style: none;
}
.q-box summary::-webkit-details-marker { display: none; }
.q-box summary::after { content: '▾'; margin-left: 0.5rem; color: var(--db-text-soft); }
.q-box[open] summary::after { content: '▴'; }
.q-box summary span { flex: 1; }
.q-box .q-list { margin: 0.7rem 0 0; }

@media (max-width: 800px) {
  .designs { padding: 1.25rem 1rem 2.5rem; }
  .panel-body { grid-template-columns: 1fr; }
  .viewer { position: static; }
}
</style>
