import { ref, computed } from 'vue'
import { useImageField } from '@/composables/useImageField'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import { apiUrl, mediaUrl } from '@/config/api'

/**
 * 整條設計流程的狀態與 API 呼叫。
 *
 * 為什麼是「模組層級單例」而不是每次呼叫都建一份：新版 UI 是線性精靈，每一步都是
 * 獨立元件，切步驟時前一個元件會被卸載。狀態放在模組層級，切步驟（甚至跑去個人專區
 * 再回來）都不會掉資料——這是舊版把全部狀態塞在 HomeView 裡時「免費」得到的性質，
 * 拆成多個元件後必須自己維持。
 *
 * 邏輯全部沿用舊 HomeView.vue，只多了 (a) 步驟導航 (b) 上傳空間照片這條路徑
 * (c) 環景／估價從 ResultPanel 移上來（設計稿把它們拆成獨立步驟）。
 */

/* ── 各入口路徑的步驟表 ────────────────────────────────────────
   Figma 的流程列在不同入口下步數不同（frame 10 是六步、frame 16 是五步），
   所以步驟是資料驅動的，不是寫死的 1/2。

   與設計稿的差異：360°環景不獨立成一步。它耗時 30–60 秒且不是每次都要看，
   所以沿用舊版的做法——留在「3D渲染圖」這一步，使用者按了才生成。 */
export const STEP_FLOWS = {
  // 從繪製平面設計圖開始
  generate: [
    { key: 'space',  label: '空間設定' },
    { key: 'plan',   label: '繪製平面圖' },
    { key: 'render', label: '3D渲染圖' },
    { key: 'refine', label: '微調編輯' },
    { key: 'budget', label: '預算估計' },
  ],
  // 上傳現有空間照片
  photo: [
    { key: 'photo',  label: '空間照片上傳' },
    { key: 'render', label: '3D渲染圖' },
    { key: 'refine', label: '微調編輯' },
    { key: 'budget', label: '預算估計' },
  ],
  // 從零開始，直接描述理想空間
  skip: [
    { key: 'space',  label: '空間設定' },
    { key: 'render', label: '3D渲染圖' },
    { key: 'refine', label: '微調編輯' },
    { key: 'budget', label: '預算估計' },
  ],
  // 上傳 2D 平面配置圖。後端（/api/parse-floor-plan）與底下的 useUploadedPlan
  // 都還在，只是目前沒有入口卡片指向它；要重新開放時把 StartView 加一張卡即可。
  upload: [
    { key: 'planUpload', label: '上傳平面圖' },
    { key: 'plan',       label: '繪製平面圖' },
    { key: 'render',     label: '3D渲染圖' },
    { key: 'refine',     label: '微調編輯' },
    { key: 'budget',     label: '預算估計' },
  ],
}

const STYLE_PAGE_SIZE = 10
const ROOM_TYPE_LABEL = { living_room: '客廳', bedroom: '臥室', kitchen: '廚房', study: '書房', dining_room: '餐廳' }

export const ASPECT_OPTIONS = [
  { value: 'auto', label: '自動' },
  { value: '1:1',  label: '1:1 正方形' },
  { value: '4:3',  label: '4:3 橫式' },
  { value: '3:4',  label: '3:4 直式' },
  { value: '16:9', label: '16:9 寬螢幕' },
  { value: '9:16', label: '9:16 直式寬螢幕' },
]
export const FAMILY_OPTIONS = [
  { value: 'children',   label: '有小孩' },
  { value: 'wheelchair', label: '有輪椅使用者' },
  { value: 'pets',       label: '有寵物' },
]
export const FENGSHUI_OPTIONS = [
  { value: 'bed_not_facing_door',    label: '床不對門' },
  { value: 'sofa_not_back_to_door',  label: '沙發不背門' },
  { value: 'desk_not_facing_window', label: '書桌不背窗' },
]

/* ══ 模組層級狀態 ══════════════════════════════════════════ */

// ── 路徑與步驟 ──
const planSource = ref('generate')          // 'generate' | 'photo' | 'skip' | 'upload'
const stepIndex  = ref(0)

// ── 平面圖 ──
const floorPlanUrl      = ref('')
const floorPlanPath     = ref('')
const sceneGraph        = ref(null)
const floorPlanUpload   = useImageField()
const uploadedPlanUrl   = ref('')

// ── 佈局編輯 ──
const editPlacements     = ref([])
const roomW              = ref(5.0)
const roomD              = ref(4.0)
const roomTypeForPlan    = ref('living_room')
const layoutViewMode     = ref('2d')        // '2d' | '3d'
const layoutRenderConfig = ref(null)

// ── 空間設定表單 ──
const roomType       = ref('living_room')
const spaceSizePing  = ref(4)
const customRoomW    = ref(null)            // 公尺，null = 用坪數估算
const customRoomD    = ref(null)
const furnitureItems = ref([])
const furnitureQty   = ref({})
const extraPrompt    = ref('')
const familyNeeds    = ref([])
const fengshuiRules  = ref([])
const outputAspect   = ref('auto')

// ── 空間照片（上傳照片入口）──
const spacePhoto     = useImageField()
const spacePhotoPath = ref('')

// ── 風格 ──
const selectedStyle       = ref('auto')
const noStyleReference    = ref(false)
const styleMethod         = ref('ai_analysis')
const styleRefImage       = useImageField()
const styleOptions        = ref([{ label: '自動', value: 'auto' }])
const styleLoading        = ref(false)
const styleError          = ref('')
const styleCandidates     = ref([])
const styleCandidatePool  = ref([])
const candidatesLoading   = ref(false)
const candidatesSearched  = ref(false)
const confirmedStyle      = ref(null)
const matchedStylePreview = ref(null)

// ── 結果 ──
const result     = ref(null)
const loading    = ref(false)
const loadingMsg = ref({ title: '', sub: '' })
const error      = ref('')
const submitKey  = ref(0)
let currentRequestId = 0

// ── 微調 ──
const spaceImage         = useImageField()
const lastGeneratedImage = ref(null)
const manualMaskPath     = ref('')
const brushSize          = ref(32)
const drawMode           = ref('draw')
const editScope          = ref(0.6)
const textPrompt         = ref('')
const refineCanvasRef    = ref(null)

// ── 360° 環景（原本在 ResultPanel，設計稿拆成獨立步驟）──
const panoLoading = ref(false)
const panoUrl     = ref(null)
const panoError   = ref('')

// ── 家具估價（原本在 ResultPanel）──
const quotationLoading = ref(false)
const quotationError   = ref('')

// ── 收藏這個設計（預算估計步驟最後一顆按鈕）──
// 每次 /api/generate 都已經自動存進 artifacts/history.json 了，收藏不是另開一份
// 清單，只是在同一筆紀錄上標記 favorited=true，讓它在歷史紀錄裡好找、不會被
// 使用者自己在歷史紀錄頁批次刪除時誤刪。
const favoriteLoading = ref(false)
const favoriteError   = ref('')

let searchTimer = null
let floorPlanUpdateTimer = null

/* ══ 衍生值 ══════════════════════════════════════════════ */

const steps        = computed(() => STEP_FLOWS[planSource.value] || STEP_FLOWS.generate)
const currentStep  = computed(() => steps.value[stepIndex.value]?.key || 'space')
const isLastStep   = computed(() => stepIndex.value >= steps.value.length - 1)

const baseImagePreview = computed(
  () => lastGeneratedImage.value?.url || spaceImage.preview || spacePhoto.preview || null,
)

const showSuggestions = computed(
  () => !styleRefImage.file &&
    (styleCandidates.value.length > 0 || candidatesLoading.value || candidatesSearched.value),
)

/* ══ 導航 ══════════════════════════════════════════════ */

function goStep(i) {
  stepIndex.value = Math.max(0, Math.min(steps.value.length - 1, i))
  error.value = ''
}
function nextStep() { goStep(stepIndex.value + 1) }
function prevStep() { goStep(stepIndex.value - 1) }

function startFlow(source) {
  resetFlow()
  planSource.value = source
  stepIndex.value = 0
}

function resetFlow() {
  planSource.value = 'generate'
  stepIndex.value = 0
  floorPlanUrl.value = ''
  floorPlanPath.value = ''
  sceneGraph.value = null
  editPlacements.value = []
  clearTimeout(floorPlanUpdateTimer); floorPlanUpdateTimer = null
  clearTimeout(searchTimer); searchTimer = null
  layoutViewMode.value = '2d'
  layoutRenderConfig.value = null
  floorPlanUpload.remove()
  uploadedPlanUrl.value = ''
  spacePhoto.remove()
  spacePhotoPath.value = ''
  spaceImage.remove()
  styleRefImage.remove()
  result.value = null
  error.value = ''
  loading.value = false
  styleCandidates.value = []
  styleCandidatePool.value = []
  candidatesSearched.value = false
  confirmedStyle.value = null
  matchedStylePreview.value = null
  lastGeneratedImage.value = null
  manualMaskPath.value = ''
  textPrompt.value = ''
  panoUrl.value = null
  panoError.value = ''
  panoLoading.value = false
  quotationError.value = ''
}

/* ══ 共用 ══════════════════════════════════════════════ */

async function uploadFile(file) {
  const body = new FormData()
  body.append('file', file)
  const res = await fetch(apiUrl('/api/upload-image'), { method: 'POST', body })
  if (!res.ok) throw new Error(`${res.status}`)
  return (await res.json()).path
}

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
      ...data.map(({ style_name, style_id }) => ({ label: `${style_name} (${style_id})`, value: style_id })),
    ]
    styleError.value = ''
  } catch { styleError.value = '無法載入風格選項，請稍後重試' }
  finally { styleLoading.value = false }
}

/* ══ 風格搜尋（沿用舊 HomeView 的錨定／輪替行為） ══════════ */

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
  const diverse = !anchor && !extraPrompt.value.trim() && !sid
  try {
    const res = await fetch(
      apiUrl(`/api/style-search?query=${encodeURIComponent(q)}&style_id=${encodeURIComponent(sid)}&top_k=24${diverse ? '&diverse=true' : ''}`),
    )
    if (res.ok) {
      const data = await res.json()
      let pool = (Array.isArray(data) ? data : [])
        .slice().sort((a, b) => Number(b?.similarity ?? 0) - Number(a?.similarity ?? 0))
      if (anchor) pool = [anchor, ...pool.filter(c => c.image_url !== anchor.image_url)]
      styleCandidatePool.value = pool
      const sorted = pool.slice(0, STYLE_PAGE_SIZE)
      styleCandidates.value = sorted
      matchedStylePreview.value = sorted[0]
        ? { image_url: sorted[0].image_url, style_name: sorted[0].style_name, similarity: sorted[0].similarity }
        : null
      const keep = confirmedStyle.value && sorted.find(c => c.image_url === confirmedStyle.value.image_url)
      confirmedStyle.value = keep || (!diverse && sorted[0]) || null
    }
  } catch {}
  finally { candidatesLoading.value = false; candidatesSearched.value = true }
}

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

function confirmStyle(candidate) { confirmedStyle.value = candidate }
function clearConfirmedStyle()   { confirmedStyle.value = null }

/* ══ Step: 空間設定 → 產生 2D 平面圖 ══════════════════════ */

async function submitLayout() {
  // 這條路徑的第一頁已經不放描述欄位了（描述移到選風格那一步），
  // 所以訊息只提家具，不要叫使用者去找一個畫面上沒有的欄位。
  if (!furnitureItems.value.length && !extraPrompt.value.trim()) {
    error.value = '請至少選擇一件要擺放的家具'
    return
  }
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '生成 2D 平面圖中', sub: 'AI 計算家具配置，通常約 10 秒' }
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
        furniture_list:  furnitureItems.value.flatMap(
          t => Array(Math.max(1, furnitureQty.value[t] || 1)).fill(t),
        ),
        text_prompt:    extraPrompt.value,
        family_needs:   familyNeeds.value,
        fengshui_rules: fengshuiRules.value,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId !== currentRequestId) return
    floorPlanUrl.value  = data.floor_plan_url || ''
    floorPlanPath.value = data.floor_plan_path || ''
    sceneGraph.value    = data.scene_graph || null
    layoutRenderConfig.value = data.layout_render_config || null
    editPlacements.value = (data.scene_graph?.furniture_placements || []).map((p, i) => ({
      id: p.id || `item_${i}`, type: p.type, x: p.x, y: p.y, w: p.w, h: p.h, rotation: p.rotation || 0,
    }))
    roomW.value = data.room_w || 5.0
    roomD.value = data.room_d || 4.0
    roomTypeForPlan.value = data.room_type || roomType.value
    nextStep()
    scheduleSearch()
  } catch (e) {
    if (requestId === currentRequestId) error.value = `生成平面圖失敗：${e.message}`
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

/* ══ Step: 上傳 2D 平面配置圖（保留，目前無入口） ══════════ */

async function useUploadedPlan() {
  if (!floorPlanUpload.file) {
    error.value = '請先上傳平面配置圖'
    return
  }
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '解析平面圖中', sub: 'AI 辨識平面圖上的家具配置' }
  result.value = null
  try {
    const path = await uploadFile(floorPlanUpload.file)
    if (requestId !== currentRequestId) return
    uploadedPlanUrl.value = mediaUrl(path)
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

    const placements = (data.furniture_placements || []).map((p, i) => ({
      id: p.id || `item_${i}`, type: p.type, x: p.x, y: p.y, w: p.w, h: p.h, rotation: p.rotation || 0,
    }))
    if (placements.length) {
      floorPlanPath.value = data.floor_plan_path || path
      floorPlanUrl.value = data.floor_plan_url || mediaUrl(path)
      sceneGraph.value = data.scene_graph || null
      layoutRenderConfig.value = data.layout_render_config || null
      editPlacements.value = placements
    } else {
      floorPlanPath.value = path
      floorPlanUrl.value = mediaUrl(path)
      sceneGraph.value = null
      editPlacements.value = []
    }
    roomW.value = data.room_w || 5.0
    roomD.value = data.room_d || 4.0
    roomTypeForPlan.value = data.room_type || roomType.value
    nextStep()
    if (extraPrompt.value.trim()) scheduleSearch()
  } catch (e) {
    if (requestId === currentRequestId) error.value = `解析平面圖失敗：${e.message}`
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

/* ══ Step: 上傳空間照片 ════════════════════════════════════
   照片走 /api/generate 的 initial_image_path：visual_preprocessing 會抽視覺特徵、
   requirement agent 會把照片一起餵給 Gemini，所以不需要新的後端端點。 */

async function submitPhoto() {
  if (!spacePhoto.file) {
    error.value = '請先上傳空間照片'
    return
  }
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '上傳空間照片中', sub: '準備分析你的空間' }
  try {
    spacePhotoPath.value = await uploadFile(spacePhoto.file)
    nextStep()
    scheduleSearch()
  } catch (e) {
    error.value = `上傳失敗：${e.message}`
  } finally {
    loading.value = false
  }
}

/* ══ 佈局編輯 ══════════════════════════════════════════════ */

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
    floorPlanUrl.value = (data.floor_plan_url || '') + `?t=${Date.now()}`
    floorPlanPath.value = data.floor_plan_path || floorPlanPath.value
    if (sceneGraph.value && data.floor_plan_path) {
      sceneGraph.value = { ...sceneGraph.value, floor_plan_path: data.floor_plan_path }
    }
  } catch (e) {
    error.value = `更新平面圖失敗：${e.message}`
  }
}

/* ══ Step: 3D 渲染 ════════════════════════════════════════ */

async function submit3D() {
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
  loadingMsg.value = { title: '生成 3D 渲染圖中', sub: 'AI 將平面配置轉為立體室內透視，通常約 30–60 秒' }
  panoUrl.value = null
  panoError.value = ''
  try {
    let style_reference_image_path
    if (!noStyleReference.value) {
      if (styleRefImage.file) style_reference_image_path = await uploadFile(styleRefImage.file)
      else if (confirmedStyle.value?.image_url) style_reference_image_path = confirmedStyle.value.image_url
    }

    const editedSceneGraph = editPlacements.value.length
      ? {
          ...(sceneGraph.value || {}),
          furniture_placements: editPlacements.value,
          floor_plan_path: floorPlanPath.value || sceneGraph.value?.floor_plan_path,
        }
      : undefined

    // 跳過排版時沒有 scene_graph、沒有平面圖、也沒有照片，房型與坪數就沒有任何
    // 欄位可以承載（DesignRequest 沒有 room_type / space_size）。折進 text_prompt，
    // 使用者在第一步選的東西才真的會影響生成結果，而不是選了等於沒選。
    const noSpatialInput = !editedSceneGraph && !floorPlanPath.value && !spacePhotoPath.value
    const spacePreamble = noSpatialInput
      ? `${ROOM_TYPE_LABEL[roomTypeForPlan.value] || ''}，約 ${spaceSizePing.value} 坪。`
      : ''

    const res = await fetch(apiUrl('/api/generate'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text_prompt:      (spacePreamble + extraPrompt.value).trim(),
        edit_scope:       1.0,
        style_profile_id: !noStyleReference.value && selectedStyle.value !== 'auto'
          ? selectedStyle.value
          : !noStyleReference.value ? confirmedStyle.value?.style_id || undefined : undefined,
        style_reference_image_path,
        no_style_reference: noStyleReference.value,
        refine_mode:        false,
        output_aspect:      outputAspect.value,
        style_method:       styleMethod.value,
        family_needs:       familyNeeds.value,
        fengshui_rules:     fengshuiRules.value,
        // 上傳照片路徑：把照片當作生成的起始影像
        initial_image_path: spacePhotoPath.value || undefined,
        floor_plan_path:    floorPlanPath.value || undefined,
        scene_graph:        editedSceneGraph,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId === currentRequestId) {
      result.value = data
      if (data.generated_image_path) {
        lastGeneratedImage.value = { path: data.generated_image_path, url: data.generated_image_url || null }
      }
    }
  } catch (e) {
    if (requestId === currentRequestId) error.value = `生成渲染圖失敗：${e.message}`
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

/* ══ Step: 360° 環景 ══════════════════════════════════════ */

async function generatePanorama() {
  const r = result.value
  if (!r?.task_id || !r?.generated_image_path) return
  panoLoading.value = true
  panoError.value = ''
  try {
    const res = await fetch(apiUrl('/api/generate-panorama'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_id: r.task_id,
        image_path: r.generated_image_path,
        depth_path: r.vision_features?.depth || null,
        prompt: r.structured_requirement?.meta?.design_goal || '',
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    panoUrl.value = data.room_panorama_url
  } catch (e) {
    panoError.value = e.message
  } finally {
    panoLoading.value = false
  }
}

/* ══ Step: 微調編輯 ══════════════════════════════════════ */

async function handleMaskReady(blob) {
  const file = new File([blob], 'mask.png', { type: 'image/png' })
  manualMaskPath.value = await uploadFile(file)
}

async function submitRefine() {
  if (!textPrompt.value.trim()) { error.value = '請輸入調整需求'; return }
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '套用微調中', sub: 'AI 只重繪你塗抹的區域，其餘保持不變' }
  try {
    let mask_image_path
    const maskBlob = await refineCanvasRef.value?.getMaskBlob()
    if (maskBlob) {
      mask_image_path = await uploadFile(new File([maskBlob], 'mask.png', { type: 'image/png' }))
      manualMaskPath.value = mask_image_path
    }

    const initial_image_path = lastGeneratedImage.value?.path
      || spacePhotoPath.value
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
      result.value = { ...(result.value || {}), ...data }
      if (data.generated_image_path) {
        lastGeneratedImage.value = { path: data.generated_image_path, url: data.generated_image_url || null }
      }
    }
  } catch (e) {
    if (requestId === currentRequestId) error.value = `微調失敗：${e.message}`
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

/* ══ Step: 預算估計 ══════════════════════════════════════ */

async function fetchQuotation() {
  const imagePath = lastGeneratedImage.value?.path || result.value?.generated_image_path
  if (!imagePath) return
  const { selectedFurniture } = useFurnitureSelection()
  quotationLoading.value = true
  quotationError.value = ''
  try {
    const res = await fetch(apiUrl('/api/quotation'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_path: imagePath,
        structured_requirement: result.value?.structured_requirement || null,
        selected_furniture: selectedFurniture.value,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    result.value = { ...(result.value || {}), quotation_result: data }
  } catch (e) {
    quotationError.value = e.message || '估價失敗，請稍後再試'
  } finally {
    quotationLoading.value = false
  }
}

/* ══ 收藏這個設計 ══════════════════════════════════════ */

async function toggleFavoriteDesign(next) {
  const taskId = result.value?.task_id
  if (!taskId) return
  const favorited = next ?? !result.value?.favorited
  favoriteLoading.value = true
  favoriteError.value = ''
  try {
    const res = await fetch(apiUrl(`/api/history/${encodeURIComponent(taskId)}/favorite`), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ favorited }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    result.value = { ...(result.value || {}), favorited }
  } catch (e) {
    favoriteError.value = '收藏失敗，請稍後再試'
  } finally {
    favoriteLoading.value = false
  }
}

/* ══════════════════════════════════════════════════════ */

export function useDesignFlow() {
  return {
    // 路徑 / 步驟
    planSource, stepIndex, steps, currentStep, isLastStep,
    goStep, nextStep, prevStep, startFlow, resetFlow,
    // 平面圖
    floorPlanUrl, floorPlanPath, sceneGraph, floorPlanUpload, uploadedPlanUrl,
    // 佈局
    editPlacements, roomW, roomD, roomTypeForPlan, layoutViewMode, layoutRenderConfig,
    onEditorChange, updateFloorPlan,
    // 空間設定
    roomType, spaceSizePing, customRoomW, customRoomD,
    furnitureItems, furnitureQty, extraPrompt, familyNeeds, fengshuiRules, outputAspect,
    // 空間照片
    spacePhoto, spacePhotoPath,
    // 風格
    selectedStyle, noStyleReference, styleMethod, styleRefImage,
    styleOptions, styleLoading, styleError,
    styleCandidates, candidatesLoading, candidatesSearched, confirmedStyle, matchedStylePreview,
    showSuggestions, fetchStyleOptions, fetchStyleCandidates, showNextRound, scheduleSearch,
    confirmStyle, clearConfirmedStyle,
    // 結果
    result, loading, loadingMsg, error, submitKey,
    // 微調
    spaceImage, lastGeneratedImage, manualMaskPath, brushSize, drawMode, editScope,
    textPrompt, refineCanvasRef, baseImagePreview, handleMaskReady,
    // 環景
    panoLoading, panoUrl, panoError, generatePanorama,
    // 估價
    quotationLoading, quotationError, fetchQuotation,
    // 收藏
    favoriteLoading, favoriteError, toggleFavoriteDesign,
    // 動作
    uploadFile, submitLayout, useUploadedPlan, submitPhoto, submit3D, submitRefine,
  }
}
