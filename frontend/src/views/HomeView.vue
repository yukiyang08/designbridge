<script setup>
import { ref, onMounted, watch, computed, defineAsyncComponent } from 'vue'
import { useImageField } from '@/composables/useImageField'
import designbridgeLogo from '../../asset/designbridge_logo.png'
import SidebarForm from '@/components/SidebarForm.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import StyleSuggestions from '@/components/StyleSuggestions.vue'
import LayoutEditor from '@/components/LayoutEditor.vue'
import RefineCanvas from '@/components/RefineCanvas.vue'
import { API_BASE, apiUrl, mediaUrl } from '@/config/api'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'

// three.js 是重依賴（~700KB），非同步載入，只有切到 3D 檢視時才下載
const LayoutPreview3D = defineAsyncComponent(() => import('@/components/LayoutPreview3D.vue'))

const { selectedCount: furnitureSelectedCount } = useFurnitureSelection()

// ── Two-step state ────────────────────────────────────────────
const designStep   = ref(1)   // 1 = layout input, 2 = style + 3D
const floorPlanUrl  = ref('')
const floorPlanPath = ref('')
const sceneGraph    = ref(null)
// Step 1 plan source: 'generate' = AI auto-layout, 'upload' = user supplies a floor plan
const planSource     = ref('generate')
const floorPlanUpload = useImageField()
const uploadedPlanUrl = ref('')   // original uploaded plan, kept for side-by-side reference

// ── Layout editor state ───────────────────────────────────────
const editPlacements = ref([])   // editable copy of furniture_placements
const roomW = ref(5.0)
const roomD = ref(4.0)
const roomTypeForPlan = ref('living_room')
const layoutViewMode = ref('2d')        // '2d' | '3d' — toggle for the editable layout view
const layoutRenderConfig = ref(null)    // furniture heights/colors/camera for the 3D preview
// LayoutPreview3D wants { furniture_placements } — same shape as scene_graph — so both
// views (2D drag editor, 3D drag preview) read/write the one editPlacements array.
const editSceneGraph = computed(() => ({ furniture_placements: editPlacements.value }))
const editSpaceInfo = computed(() => ({ estimated_size: { width: roomW.value, depth: roomD.value } }))

// ── Step 1 form values ────────────────────────────────────────
const roomType       = ref('living_room')
const spaceSizePing  = ref(4)
const customRoomW    = ref(null)   // 公尺，null = 用坪數估算（Step 1「自訂長寬」欄位）
const customRoomD    = ref(null)
const furnitureItems = ref([])
const furnitureQty   = ref({})
const extraPrompt    = ref('')
const familyNeeds    = ref([])
const fengshuiRules  = ref([])

// ── Step 2 form values ────────────────────────────────────────
const selectedStyle    = ref('auto')
const noStyleReference = ref(false)
const styleMethod      = ref('ai_analysis')
const styleRefImage    = useImageField()

// ── Style options ─────────────────────────────────────────────
const styleOptions  = ref([{ label: '自動', value: 'auto' }])
const styleLoading  = ref(false)
const styleError    = ref('')

// ── Candidates (step 2) ───────────────────────────────────────
const styleCandidates    = ref([])
const candidatesLoading  = ref(false)
const candidatesSearched = ref(false)
const confirmedStyle     = ref(null)
const matchedStylePreview = ref(null)
// 完整候選池（後端一次多給幾張）跟目前顯示的那一頁；「下一輪」在池子裡輪替，不必重打 API
// （向量搜尋是決定性的，同樣的查詢字重打結果不會變）。
const STYLE_PAGE_SIZE = 10
const styleCandidatePool = ref([])

// ── Result / loading ──────────────────────────────────────────
const result  = ref(null)
const loading = ref(false)
const error   = ref('')
let currentRequestId = 0
const submitKey = ref(0)

// ── Refine 模式（細部編輯）─────────────────────────────────────
// 與兩段式 design 流程正交：design 產生圖，refine 在該圖上做局部重繪。
const mode = ref('design')              // 'design' | 'refine'
const spaceImage      = useImageField() // refine 模式可直接上傳一張要修的圖
const lastGeneratedImage = ref(null)    // { path, url } — design 流程產出的最新一張
const manualMaskPath  = ref('')         // 手繪遮罩上傳後的伺服器路徑
const outputAspect    = ref('auto')
const brushSize       = ref(32)
const drawMode        = ref('draw')
const refineCanvasRef = ref(null)
const editScope       = ref(0.6)
const textPrompt      = ref('')

const baseImagePreview = computed(() =>
  lastGeneratedImage.value?.url || spaceImage.preview || null
)

// Show StyleSuggestions only in step 2 before 3D result
const showSuggestions = computed(() =>
  designStep.value === 2 &&
  !result.value && !loading.value && !styleRefImage.file &&
  (styleCandidates.value.length > 0 || candidatesLoading.value || candidatesSearched.value)
)

// ── Style search ──────────────────────────────────────────────
// 房型中文標籤，Step 1 沒填「額外需求」、Step 2 也還沒選風格時，拿房型當查詢字，
// 不然風格推薦區塊在最常見的操作路徑（只選房型+家具、不打字）下永遠不會出現。
const ROOM_TYPE_LABEL = { living_room: '客廳', bedroom: '臥室', kitchen: '廚房', study: '書房' }
let searchTimer = null
// anchorSelected：手動按「找相似風格」且已經選了一張卡時，改以那張卡的風格為準去找更多
// 同類型候選，並把選中的那張釘住留在清單裡——而不是照目前文字描述重查一次、把選擇沖掉。
async function fetchStyleCandidates({ anchorSelected = false } = {}) {
  if (styleRefImage.file) return
  const anchor = anchorSelected ? confirmedStyle.value : null
  const q = anchor ? '' : (extraPrompt.value.trim() || ROOM_TYPE_LABEL[roomTypeForPlan.value] || '')
  const sid = anchor ? anchor.style_id : (selectedStyle.value !== 'auto' ? selectedStyle.value : '')
  if (!q && !sid) {
    styleCandidates.value = []
    candidatesSearched.value = false
    confirmedStyle.value = null
    matchedStylePreview.value = null
    return
  }
  candidatesLoading.value = true
  // 使用者沒寫風格描述、也沒手動選風格時，q 只是房型中文字的通用 fallback，讓後端
  // 每個風格各挑一張，而不是全域 top_k 集中命中一兩種風格。
  const diverse = !anchor && !extraPrompt.value.trim() && !sid
  try {
    const res = await fetch(
      apiUrl(`/api/style-search?query=${encodeURIComponent(q)}&style_id=${encodeURIComponent(sid)}&top_k=24${diverse ? '&diverse=true' : ''}`)
    )
    if (res.ok) {
      const data = await res.json()
      let pool = (Array.isArray(data) ? data : [])
        .slice().sort((a, b) => Number(b?.similarity ?? 0) - Number(a?.similarity ?? 0))
      if (anchor) {
        pool = [anchor, ...pool.filter((c) => c.image_url !== anchor.image_url)]
      }
      styleCandidatePool.value = pool
      const sorted = pool.slice(0, STYLE_PAGE_SIZE)
      styleCandidates.value = sorted
      matchedStylePreview.value = sorted[0]
        ? { image_url: sorted[0].image_url, style_name: sorted[0].style_name, similarity: sorted[0].similarity }
        : null
      // 只有使用者實際輸入了什麼（打了描述、選了風格、或自己點過卡片）才預設框住最高分那張；
      // 純房型 fallback 的 diverse 查詢不算「使用者的選擇」，不要自動選。已選且仍在清單中則保留。
      const keep = confirmedStyle.value
        && sorted.find(c => c.image_url === confirmedStyle.value.image_url)
      confirmedStyle.value = keep || (!diverse && sorted[0]) || null
    }
  } catch {}
  finally { candidatesLoading.value = false; candidatesSearched.value = true }
}

// 「下一輪」：沒選卡片時按的那顆按鈕。池子裡輪一頁出來顯示，不打 API（同樣的查詢字重打
// 結果不會變，輪換池子裡已經多要來的候選才會看到真的不一樣的圖）。
function showNextRound() {
  const pool = styleCandidatePool.value
  if (pool.length <= STYLE_PAGE_SIZE) return
  const rotated = [...pool.slice(STYLE_PAGE_SIZE), ...pool.slice(0, STYLE_PAGE_SIZE)]
  styleCandidatePool.value = rotated
  styleCandidates.value = rotated.slice(0, STYLE_PAGE_SIZE)
}

function scheduleSearch() {
  clearTimeout(searchTimer)
  styleCandidates.value = []
  styleCandidatePool.value = []
  candidatesSearched.value = false
  confirmedStyle.value = null
  matchedStylePreview.value = null
  searchTimer = setTimeout(fetchStyleCandidates, 600)
}

// skip 模式（直接生成）沒有 designStep=2 的過場，AI 推薦風格要在 Step 1 就即時查
watch([selectedStyle, extraPrompt], () => {
  if (designStep.value === 2 || planSource.value === 'skip') scheduleSearch()
})
watch(planSource, (v) => { if (v === 'skip' && designStep.value === 1) scheduleSearch() })
watch(() => styleRefImage.file, (f) => {
  if (f) { clearTimeout(searchTimer); styleCandidates.value = []; candidatesSearched.value = false }
  else styleMethod.value = 'ai_analysis'
})

// ── Backend wait ──────────────────────────────────────────────
async function waitForBackend(maxWaitMs = 120000, intervalMs = 2000) {
  const deadline = Date.now() + maxWaitMs
  while (Date.now() < deadline) {
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 4000)
      const res = await fetch(apiUrl('/api/health'), { signal: ctrl.signal })
      clearTimeout(timer)
      if (res.ok) return true
    } catch {}
    styleError.value = '等待後端啟動中…（請確認已執行 python -m uvicorn api:app）'
    await new Promise(r => setTimeout(r, intervalMs))
  }
  return false
}

async function fetchStyleOptions() {
  styleLoading.value = true
  styleError.value = ''
  if (!(await waitForBackend())) {
    styleError.value = '無法連線後端，請確認伺服器是否已啟動'
    styleLoading.value = false
    return
  }
  try {
    const res = await fetch(apiUrl('/api/style-profiles'))
    if (!res.ok) throw new Error('載入風格選項失敗')
    const data = await res.json()
    styleOptions.value = [
      { label: '自動', value: 'auto' },
      ...data.map(({ style_name, style_id }) => ({
        label: `${style_name} (${style_id})`,
        value: style_id,
      })),
    ]
    styleError.value = ''
  } catch { styleError.value = '無法載入風格選項，請稍後重試' }
  finally { styleLoading.value = false }
}

async function uploadFile(file) {
  const body = new FormData()
  body.append('file', file)
  const res = await fetch(apiUrl('/api/upload-image'), { method: 'POST', body })
  if (!res.ok) throw new Error(`${res.status}`)
  return (await res.json()).path
}

// ── Step 1: generate layout ───────────────────────────────────
async function handleSubmitLayout() {
  if (!furnitureItems.value.length && !extraPrompt.value.trim()) {
    error.value = '請至少選擇一件家具或輸入描述'
    return
  }
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  result.value = null
  try {
    const res = await fetch(apiUrl('/api/generate-layout'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        room_type:       roomType.value,
        space_size_ping: spaceSizePing.value,
        room_w:          customRoomW.value || undefined,
        room_d:          customRoomD.value || undefined,
        // expand each furniture type by its chosen quantity, e.g. chair×3
        furniture_list:  furnitureItems.value.flatMap(
          t => Array(Math.max(1, furnitureQty.value[t] || 1)).fill(t)
        ),
        text_prompt:     extraPrompt.value,
        family_needs:    familyNeeds.value,
        fengshui_rules:  fengshuiRules.value,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId !== currentRequestId) return
    floorPlanUrl.value  = data.floor_plan_url || ''
    floorPlanPath.value = data.floor_plan_path || ''
    sceneGraph.value    = data.scene_graph || null
    layoutRenderConfig.value = data.layout_render_config || null
    // seed the editable layout
    const placements = (data.scene_graph?.furniture_placements || [])
      .map((p, i) => ({ id: p.id || `item_${i}`, type: p.type, x: p.x, y: p.y, w: p.w, h: p.h, rotation: p.rotation || 0 }))
    editPlacements.value = placements
    roomW.value = data.room_w || 5.0
    roomD.value = data.room_d || 4.0
    roomTypeForPlan.value = data.room_type || roomType.value
    designStep.value = 2
    // 進 Step 2 就查風格推薦——即使沒打額外需求，fetchStyleCandidates 也會退回用房型當查詢字
    scheduleSearch()
  } catch (e) {
    if (requestId === currentRequestId) error.value = e.message
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

// ── Step 1 (alt): use an uploaded floor plan directly ─────────
async function handleUseUploadedPlan() {
  if (!floorPlanUpload.file) {
    error.value = '請先上傳平面配置圖'
    return
  }
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  result.value = null
  try {
    const path = await uploadFile(floorPlanUpload.file)
    if (requestId !== currentRequestId) return
    uploadedPlanUrl.value = mediaUrl(path)

    // Parse the plan with Gemini vision → structured furniture coords, so the upload
    // drives the SAME accurate layout-projection pipeline (and becomes editable).
    const res = await fetch(apiUrl('/api/parse-floor-plan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_path: path,
        room_type: roomType.value,
        space_size_ping: spaceSizePing.value,
        room_w: customRoomW.value || undefined,
        room_d: customRoomD.value || undefined,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId !== currentRequestId) return

    const placements = (data.furniture_placements || [])
      .map((p, i) => ({ id: p.id || `item_${i}`, type: p.type, x: p.x, y: p.y, w: p.w, h: p.h, rotation: p.rotation || 0 }))

    if (placements.length) {
      // Parsed OK → treat exactly like an AI-generated layout (editable + accurate path)
      floorPlanPath.value = data.floor_plan_path || path
      floorPlanUrl.value = data.floor_plan_url || mediaUrl(path)
      sceneGraph.value = data.scene_graph || null
      layoutRenderConfig.value = data.layout_render_config || null
      editPlacements.value = placements
    } else {
      // Gemini found nothing → fall back to using the raw image as a Kontext guide
      floorPlanPath.value = path
      floorPlanUrl.value = mediaUrl(path)
      sceneGraph.value = null
      editPlacements.value = []
    }
    roomW.value = data.room_w || 5.0
    roomD.value = data.room_d || 4.0
    roomTypeForPlan.value = data.room_type || roomType.value
    designStep.value = 2
    if (extraPrompt.value.trim()) scheduleSearch()
  } catch (e) {
    if (requestId === currentRequestId) error.value = `解析平面圖失敗：${e.message}`
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

// ── Layout editor ─────────────────────────────────────────────
// 拖動/加/刪/轉家具都是 local state，畫面已經即時反應；平面圖 PNG 快照的重繪走 debounce
// 自動觸發（跟 scheduleSearch 同一招），使用者不用再手動按「更新平面圖」。
let floorPlanUpdateTimer = null
function onEditorChange(next) {
  editPlacements.value = next
  clearTimeout(floorPlanUpdateTimer)
  floorPlanUpdateTimer = setTimeout(() => {
    floorPlanUpdateTimer = null
    updateFloorPlan()
  }, 500)
}

async function updateFloorPlan() {
  if (!editPlacements.value.length) return
  try {
    const res = await fetch(apiUrl('/api/render-floor-plan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        furniture_placements: editPlacements.value,
        room_w: roomW.value,
        room_d: roomD.value,
        room_type: roomTypeForPlan.value,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    // cache-bust so the <img> reloads
    floorPlanUrl.value = (data.floor_plan_url || '') + `?t=${Date.now()}`
    floorPlanPath.value = data.floor_plan_path || floorPlanPath.value
    // keep the scene graph's embedded floor_plan_path in sync, otherwise the 3D
    // render would still be guided by the original Step-1 plan (see handleSubmit3D)
    if (sceneGraph.value && data.floor_plan_path) {
      sceneGraph.value = { ...sceneGraph.value, floor_plan_path: data.floor_plan_path }
    }
  } catch (e) {
    error.value = `更新平面圖失敗：${e.message}`
  }
}

// ── Step 2: generate 3D render ────────────────────────────────
async function handleSubmit3D() {
  // skip 模式（直接生成）在 Step 1 就直接送出，designStep 還沒切過；切到 2 才能
  // 用到既有的 loading/ResultPanel 顯示邏輯（那些只在 designStep===2 的模板裡）。
  designStep.value = 2
  // 把還沒觸發的平面圖自動更新（debounce 中）補跑完，3D 渲染才不會用到過期的 PNG。
  // （上傳平面圖沒有編輯器，這裡永遠不會有 pending timer。）
  if (floorPlanUpdateTimer) {
    clearTimeout(floorPlanUpdateTimer)
    floorPlanUpdateTimer = null
    await updateFloorPlan()
  }
  const requestId = ++currentRequestId
  submitKey.value++
  error.value = ''
  result.value = null
  loading.value = true
  try {
    let style_reference_image_path
    if (!noStyleReference.value) {
      if (styleRefImage.file) {
        style_reference_image_path = await uploadFile(styleRefImage.file)
      } else if (confirmedStyle.value?.image_url) {
        style_reference_image_path = confirmedStyle.value.image_url
      }
    }

    // With furniture coords (AI layout OR a parsed upload): fold the edited positions
    // back into the scene graph so the render follows the accurate layout-projection
    // path. Without coords (an upload Gemini couldn't parse): send no scene_graph and
    // let the backend use the raw floor_plan_path as a Kontext structural guide.
    const editedSceneGraph = editPlacements.value.length
      ? { ...(sceneGraph.value || {}), furniture_placements: editPlacements.value, floor_plan_path: floorPlanPath.value || sceneGraph.value?.floor_plan_path }
      : undefined

    const res = await fetch(apiUrl('/api/generate'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text_prompt:               extraPrompt.value,
        edit_scope:                1.0,
        style_profile_id:          !noStyleReference.value && selectedStyle.value !== 'auto'
          ? selectedStyle.value
          : !noStyleReference.value ? confirmedStyle.value?.style_id || undefined : undefined,
        style_reference_image_path,
        no_style_reference:        noStyleReference.value,
        refine_mode:               false,
        output_aspect:             outputAspect.value,
        style_method:              styleMethod.value,
        floor_plan_path:           floorPlanPath.value || undefined,
        scene_graph:               editedSceneGraph,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId === currentRequestId) {
      result.value = data
      // 記下這張圖，讓 refine 模式可以直接在它上面做局部重繪
      if (data.generated_image_path) {
        lastGeneratedImage.value = {
          path: data.generated_image_path,
          url: data.generated_image_url || null,
        }
      }
    }
  } catch (e) {
    if (requestId === currentRequestId) error.value = e.message
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

function handleConfirmStyle(candidate) { confirmedStyle.value = candidate }
function handleClearConfirmedStyle()   { confirmedStyle.value = null }
function resetToStep1() {
  designStep.value = 1
  floorPlanUrl.value = ''
  floorPlanPath.value = ''
  sceneGraph.value = null
  editPlacements.value = []
  clearTimeout(floorPlanUpdateTimer)
  floorPlanUpdateTimer = null
  layoutViewMode.value = '2d'
  layoutRenderConfig.value = null
  floorPlanUpload.remove()
  uploadedPlanUrl.value = ''
  result.value = null
  error.value = ''
  styleCandidates.value = []
  styleCandidatePool.value = []
  candidatesSearched.value = false
  confirmedStyle.value = null
  matchedStylePreview.value = null
}

// ResultPanel 的「細部微調」按鈕：切到 refine 模式，以當前生圖為基底
function handleRefine() {
  mode.value = 'refine'
}

// ResultPanel 按下「取得家具報價／重新估價」後，把結果併回 result
function handleQuotationLoaded(data) {
  if (result.value) result.value.quotation_result = data
}

async function handleMaskReady(blob) {
  const file = new File([blob], 'mask.png', { type: 'image/png' })
  manualMaskPath.value = await uploadFile(file)
}

// refine 送出：從 RefineCanvas 取得遮罩後送 API
async function handleRefineSubmit() {
  if (!textPrompt.value.trim()) { error.value = '請輸入調整需求'; return }
  const requestId = ++currentRequestId
  error.value = ''
  result.value = null
  loading.value = true
  try {
    let mask_image_path
    const maskBlob = await refineCanvasRef.value?.getMaskBlob()
    if (maskBlob) {
      mask_image_path = await uploadFile(new File([maskBlob], 'mask.png', { type: 'image/png' }))
      manualMaskPath.value = mask_image_path
    }

    const initial_image_path = lastGeneratedImage.value?.path
      || (spaceImage.file ? await uploadFile(spaceImage.file) : undefined)

    const res = await fetch(apiUrl('/api/generate'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text_prompt: textPrompt.value,
        edit_scope: editScope.value,
        initial_image_path,
        no_style_reference: true,
        refine_mode: true,
        output_aspect: outputAspect.value,
        mask_image_path,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId === currentRequestId) {
      result.value = data
      if (data.generated_image_path) {
        lastGeneratedImage.value = {
          path: data.generated_image_path,
          url: data.generated_image_url || null,
        }
      }
    }
  } catch (e) {
    if (requestId === currentRequestId) error.value = e.message
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

onMounted(fetchStyleOptions)
</script>

<template>
  <div class="page">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo">
          <img :src="designbridgeLogo" alt="DesignBridge" class="logo-img" />
        </div>

        <div class="mode-tabs">
          <button
            :class="['mode-tab', { active: mode === 'design' }]"
            @click="mode = 'design'"
          >
            裝潢圖生成
          </button>
          <button
            :class="['mode-tab', { active: mode === 'refine' }]"
            @click="mode = 'refine'"
          >
            細部編輯
          </button>
        </div>
      </div>

      <div class="sidebar-body">
        <SidebarForm
          v-model:mode="mode"
          v-model:textPrompt="textPrompt"
          v-model:brushSize="brushSize"
          v-model:drawMode="drawMode"
          :spaceImage="spaceImage"
          :baseImagePreview="baseImagePreview"
          @submit="handleRefineSubmit"
          @mask-ready="handleMaskReady"
          :designStep="designStep"
          :floorPlanUrl="floorPlanUrl"
          v-model:planSource="planSource"
          :floorPlanUpload="floorPlanUpload"
          v-model:roomType="roomType"
          v-model:spaceSizePing="spaceSizePing"
          v-model:customRoomW="customRoomW"
          v-model:customRoomD="customRoomD"
          v-model:outputAspect="outputAspect"
          v-model:furnitureItems="furnitureItems"
          v-model:furnitureQty="furnitureQty"
          v-model:extraPrompt="extraPrompt"
          v-model:familyNeeds="familyNeeds"
          v-model:fengshuiRules="fengshuiRules"
          v-model:selectedStyle="selectedStyle"
          v-model:noStyleReference="noStyleReference"
          v-model:styleMethod="styleMethod"
          :styleRefImage="styleRefImage"
          :styleOptions="styleOptions"
          :styleLoading="styleLoading"
          :styleError="styleError"
          :matchedStylePreview="matchedStylePreview"
          :loading="loading"
          :error="error"
          @submit-layout="handleSubmitLayout"
          @use-uploaded-plan="handleUseUploadedPlan"
          @submit-3d="handleSubmit3D"
          @retry-style-options="fetchStyleOptions"
        />
      </div>
    </aside>

    <RouterLink to="/furniture" class="history-fab furniture-fab" title="家具查詢">
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 9h18M5 9v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-2h8v2a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1V9M5 9V7a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v2"/>
      </svg>
      <span v-if="furnitureSelectedCount" class="fab-badge">{{ furnitureSelectedCount }}</span>
    </RouterLink>

    <RouterLink to="/cart" class="history-fab favorite-fab" title="我的收藏">
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
      </svg>
      <span v-if="furnitureSelectedCount" class="fab-badge">{{ furnitureSelectedCount }}</span>
    </RouterLink>

    <RouterLink to="/history" class="history-fab" title="歷史紀錄">
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      </svg>
    </RouterLink>

    <main class="content">

      <!-- ═══ refine 模式：在已生成的圖上局部重繪 ═══ -->
      <template v-if="mode === 'refine'">
        <div v-if="!baseImagePreview" class="placeholder">
          <div class="placeholder-inner">
            <div class="placeholder-icon">🖌️</div>
            <h2>細部編輯</h2>
            <p>先在「裝潢圖生成」產生一張設計圖，或在左側上傳一張空間圖，就能塗抹想修改的區域做局部重繪</p>
          </div>
        </div>

        <div v-else-if="loading" class="center-state">
          <div class="loading-ring"><div class="loading-spinner"></div><div class="loading-mark">✦</div></div>
          <p class="loading-title">套用微調中</p>
          <p class="loading-sub">AI 只重繪你塗抹的區域，其餘保持不變</p>
        </div>

        <div v-else-if="result?.generated_image_url" class="refine-result">
          <div class="refine-result-header">
            <span class="refine-result-label">生成結果</span>
            <button class="refine-continue-btn" @click="result = null">繼續編輯</button>
          </div>
          <img :src="result.generated_image_url" class="refine-result-img" alt="生成結果" />
        </div>

        <RefineCanvas
          v-else
          ref="refineCanvasRef"
          :imageUrl="baseImagePreview"
          :brushSize="brushSize"
          :drawMode="drawMode"
          class="refine-canvas-area"
        />
      </template>

      <!-- Step 1: empty / loading -->
      <template v-else-if="designStep === 1">
        <div v-if="loading" class="center-state">
          <div class="loading-ring"><div class="loading-spinner"></div><div class="loading-mark">✦</div></div>
          <p class="loading-title">{{ planSource === 'upload' ? '上傳平面圖中' : '生成 2D 平面圖中' }}</p>
          <p class="loading-sub">{{ planSource === 'upload' ? '處理你的平面配置圖' : 'AI 計算家具配置，通常約 10 秒' }}</p>
        </div>
        <div v-else class="placeholder">
          <div class="placeholder-inner">
            <div class="placeholder-icon">📐</div>
            <h2>設計你的空間</h2>
            <p>在左側填入坪數與預計擺放的家具，AI 會先生成 2D 平面配置圖，再進入風格選取與 3D 渲染</p>
          </div>
        </div>
      </template>

      <!-- Step 2 content -->
      <template v-else>

        <!-- Loading 3D -->
        <div v-if="loading" class="center-state">
          <div class="loading-ring"><div class="loading-spinner"></div><div class="loading-mark">✦</div></div>
          <p class="loading-title">生成 3D 渲染圖中</p>
          <p class="loading-sub">AI 將 2D 平面圖轉換為立體室內透視，通常約 30–60 秒</p>
        </div>

        <!-- 3D result -->
        <ResultPanel v-else-if="result" :key="submitKey" :result="result" :loading="false"
          @refine="handleRefine" @quotation-loaded="handleQuotationLoaded" />

        <!-- Between step 1 and 2: editable layout + style suggestions -->
        <template v-else>
          <!-- Uploaded plan: static confirmation preview, no editor (parse-but-skip-edit) -->
          <div v-if="planSource === 'upload' && floorPlanUrl" class="floor-plan-hero">
            <div class="fp-hero-label">
              <span>{{ editPlacements.length ? '已辨識你的平面圖配置' : '上傳的 2D 平面配置圖' }}</span>
              <button class="back-btn" @click="resetToStep1">← 重新上傳</button>
            </div>
            <img :src="floorPlanUrl" :alt="editPlacements.length ? '辨識後的平面配置' : '上傳的平面配置圖'" class="fp-hero-img" />

            <details v-if="editPlacements.length && uploadedPlanUrl" class="fp-png">
              <summary>對照原始上傳平面圖</summary>
              <img :src="uploadedPlanUrl" alt="原始上傳平面圖" class="fp-hero-img" />
            </details>

            <p v-if="editPlacements.length" class="fp-hero-hint">
              已辨識 {{ editPlacements.length }} 件家具。在左側選擇風格並點「生成 3D 渲染圖」即可
            </p>
            <p v-else class="fp-hero-hint">
              未能自動辨識家具，將以整張平面圖作為結構參考生成 3D。可在左側選擇風格後生成
            </p>
          </div>

          <!-- Interactive 2D/3D layout editor (AI-generated layout only) -->
          <div v-else-if="editPlacements.length || floorPlanUrl" class="floor-plan-hero">
            <div class="fp-hero-label">
              <span>{{ layoutViewMode === '3d' ? '3D 佈局預覽' : '2D 平面配置圖' }}</span>
              <div class="fp-hero-actions">
                <div class="view-toggle" v-if="editPlacements.length">
                  <button :class="{ active: layoutViewMode === '2d' }" @click="layoutViewMode = '2d'">2D</button>
                  <button :class="{ active: layoutViewMode === '3d' }" @click="layoutViewMode = '3d'">3D</button>
                </div>
                <button class="back-btn" @click="resetToStep1">← 重新規劃</button>
              </div>
            </div>

            <LayoutEditor
              v-if="layoutViewMode === '2d'"
              :placements="editPlacements"
              v-model:room-w="roomW"
              v-model:room-d="roomD"
              :room-type="roomTypeForPlan"
              @update:placements="onEditorChange"
              @room-size-changed="onEditorChange(editPlacements)"
            />
            <LayoutPreview3D
              v-else
              :scene-graph="editSceneGraph"
              :render-config="layoutRenderConfig"
              :space-info="editSpaceInfo"
              editable
              @layout-changed="onEditorChange"
            />

            <details v-if="uploadedPlanUrl" class="fp-png">
              <summary>對照原始上傳平面圖</summary>
              <img :src="uploadedPlanUrl" alt="原始上傳平面圖" class="fp-hero-img" />
            </details>

            <details v-if="floorPlanUrl" class="fp-png">
              <summary>檢視平面圖 PNG</summary>
              <img :src="floorPlanUrl" alt="2D 平面配置圖" class="fp-hero-img" />
            </details>

            <p class="fp-hero-hint">拖動調整家具位置後，在左側選擇風格並點「生成 3D 渲染圖」</p>
          </div>

          <!-- Skip 模式：沒有平面圖也沒有家具座標，只給一個回上一步的入口 -->
          <div v-else-if="planSource === 'skip'" class="floor-plan-hero">
            <div class="fp-hero-label">
              <span>不使用平面圖</span>
              <button class="back-btn" @click="resetToStep1">← 重新規劃</button>
            </div>
            <p class="fp-hero-hint">已跳過家具排版，直接依你填的描述與風格生成效果圖</p>
          </div>

          <StyleSuggestions
            v-if="showSuggestions"
            :candidates="styleCandidates"
            :confirmed="confirmedStyle"
            :loading="candidatesLoading"
            :api-base="API_BASE"
            @confirm="handleConfirmStyle"
            @clear="handleClearConfirmedStyle"
            @search="confirmedStyle ? fetchStyleCandidates({ anchorSelected: true }) : showNextRound()"
          />
        </template>

      </template>

    </main>
  </div>
</template>

<style scoped>

/* ── 模式分頁（裝潢圖生成 / 細部編輯）── */
.mode-tabs {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}

.mode-tab {
  flex: 1;
  padding: 0.6rem 0;
  border: 2px solid #d8d8d8;
  border-radius: 12px;
  background: transparent;
  color: #444;
  font-size: 0.88rem;
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s;
}
.mode-tab:hover:not(.active) {
  background: #f5f5f5;
  border-color: #bbb;
}
.mode-tab.active {
  background: linear-gradient(135deg, #8B5E3C 0%, #b07845 100%);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 4px 14px rgba(139, 94, 60, 0.35);
}

/* ── 家具查詢 / 我的收藏 FAB ── */
.furniture-fab {
  right: 7rem;
}
.favorite-fab {
  right: 4.25rem;
}
.fab-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border-radius: 999px;
  background: #c0392b;
  color: #fff;
  font-size: 0.65rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

/* ── refine 模式畫布與結果 ── */
.refine-canvas-area {
  width: 100%;
  height: 100%;
  flex: 1;
}

/* 生成中 */
.refine-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  color: #8B5E3C;
  font-size: 0.95rem;
  font-weight: 600;
}
.refine-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(139, 94, 60, 0.2);
  border-top-color: #8B5E3C;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* 生成結果 */
.refine-result {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 1.5rem;
  overflow-y: auto;
}
.refine-result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  max-width: 720px;
}
.refine-result-label {
  font-size: 1rem;
  font-weight: 700;
  color: #5c3d24;
}
.refine-continue-btn {
  padding: 0.4rem 1rem;
  border: 1.5px solid #999;
  border-radius: 8px;
  background: transparent;
  color: #444;
  font-size: 0.82rem;
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
}
.refine-continue-btn:hover { background: #f0f0f0; border-color: #666; }
.refine-result-img {
  width: 100%;
  max-width: 720px;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  object-fit: contain;
}
.page {
  display: flex; min-height: 100vh;
  background:
    radial-gradient(ellipse at 12% 20%, rgba(200,160,110,0.18) 0%, transparent 48%),
    radial-gradient(ellipse at 88% 80%, rgba(160,120,80,0.14) 0%, transparent 48%),
    linear-gradient(150deg, #fdf6ee 0%, #f5e8d8 45%, #ede0cf 100%);
}

/* ── Sidebar ── */
.sidebar {
  width: 500px; min-width: 420px;
  background: rgba(255,248,240,0.88);
  backdrop-filter: blur(18px);
  border-right: 1px solid var(--surface-border);
  display: flex; flex-direction: column; overflow-y: auto;
}
.sidebar-header {
  padding: 1.75rem 2rem 1.25rem;
  border-bottom: 1px solid rgba(180,140,100,0.14);
  flex-shrink: 0;
}
.sidebar-body { flex: 1; padding: 1.5rem 2rem 2rem; overflow-y: auto; }
.logo-img { height: auto; width: 200px; display: block; }

/* ── Content ── */
.content {
  flex: 1; min-width: 0; padding: 2.5rem 3rem;
  display: flex; flex-direction: column;
}

/* ── Center states ── */
.center-state, .placeholder {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 1rem;
}
.placeholder-inner { text-align: center; max-width: 480px; }
.placeholder-icon {
  width: 64px; height: 64px;
  background: linear-gradient(135deg, #f5e8d8, #e8d4b8);
  border-radius: 20px; display: flex; align-items: center; justify-content: center;
  font-size: 1.8rem; margin: 0 auto 1.5rem;
}
.placeholder-inner h2 { font-size: 1.6rem; font-weight: 800; color: var(--text-1); margin-bottom: 0.5rem; }
.placeholder-inner p  { font-size: 0.9rem; color: var(--text-3); line-height: 1.65; }

/* ── Loading ── */
.loading-ring { width: 64px; height: 64px; position: relative; margin-bottom: 0.5rem; }
.loading-spinner {
  position: absolute; inset: 0;
  border: 3px solid rgba(180,140,100,0.25);
  border-top-color: var(--primary); border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
.loading-mark {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem; color: var(--primary);
}
@keyframes spin { to { transform: rotate(360deg); } }
.loading-title { font-size: 1.1rem; font-weight: 700; color: var(--text-1); margin: 0; }
.loading-sub   { font-size: 0.83rem; color: var(--text-3); margin: 0; }

/* ── Floor plan hero ── */
.floor-plan-hero {
  display: flex; flex-direction: column; gap: 0.75rem;
  max-width: 1300px; width: 100%; margin: 0 auto;
}
.fp-hero-label {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 1.35rem; font-weight: 700; color: var(--text-2);
}
.back-btn {
  background: none; border: 1.5px solid #ccc; border-radius: 8px;
  padding: 0.5rem 1.2rem; font-size: 1.1rem; font-weight: 600; font-family: inherit;
  color: #666; cursor: pointer; transition: all 0.15s;
}
.back-btn:hover { border-color: #999; color: #333; }
.fp-hero-actions { display: flex; align-items: center; gap: 0.9rem; }
.view-toggle {
  display: flex; border: 1.5px solid #ccc; border-radius: 8px; overflow: hidden;
}
.view-toggle button {
  background: none; border: none; padding: 0.45rem 1rem;
  font-size: 1.1rem; font-weight: 600; font-family: inherit; color: #666; cursor: pointer;
}
.view-toggle button + button { border-left: 1.5px solid #ccc; }
.view-toggle button.active { background: #8B5E3C; color: #fff; }
.fp-hero-img {
  width: 100%; border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.12);
  border: 1px solid #ddd; margin-top: 0.5rem;
}
.fp-hero-hint { font-size: 0.8rem; color: var(--text-3); text-align: center; margin-top: 0.25rem; }

.fp-png { font-size: 0.8rem; color: var(--text-2); }
.fp-png summary { cursor: pointer; padding: 0.2rem 0; user-select: none; }

/* ── FAB ── */
.history-fab {
  position: fixed; top: 1.25rem; right: 1.5rem; z-index: 100;
  width: 40px; height: 40px; border-radius: 50%;
  background: rgba(255,248,240,0.92); backdrop-filter: blur(12px);
  border: 1px solid rgba(180,140,100,0.35);
  box-shadow: 0 2px 10px rgba(139,94,60,0.2);
  display: flex; align-items: center; justify-content: center;
  color: #8B5E3C; text-decoration: none; transition: all 0.15s;
}
.history-fab:hover { background: rgba(255,248,240,1); transform: scale(1.08); }
</style>
