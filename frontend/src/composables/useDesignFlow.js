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
  // 上傳 2D 平面配置圖。整戶圖會先用 Gemini 視覺分割房間，偵測到多間才會經過
  // 「選擇房間」這一步；只有一間就直接跳過，行為等同單純上傳一張房間圖。
  upload: [
    { key: 'planUpload', label: '上傳平面圖' },
    { key: 'roomPick',   label: '選擇房間' },
    { key: 'plan',       label: '繪製平面圖' },
    { key: 'render',     label: '3D渲染圖' },
    { key: 'refine',     label: '微調編輯' },
    { key: 'budget',     label: '預算估計' },
  ],
  // CAD 房型生成（designbridge/roomplan）：輸入幾房幾廳＋總坪數，直接切割出整層樓
  // 的房間配置（牆／門／窗），一定是多房間，所以固定經過「選擇房間」再進編輯器——
  // 跟 upload 共用 roomPick/plan 這兩個步驟 key，差別只在資料來源（見 StepRoomPick）。
  cad: [
    { key: 'roomProgram', label: '房型設定' },
    { key: 'roomPick',    label: '選擇房間' },
    { key: 'plan',        label: '繪製平面圖' },
    { key: 'render',      label: '3D渲染圖' },
    { key: 'refine',      label: '微調編輯' },
    { key: 'budget',      label: '預算估計' },
  ],
}

const STYLE_PAGE_SIZE = 10
const ROOM_TYPE_LABEL = {
  living_room: '客廳', bedroom: '臥室', kitchen: '廚房', study: '書房', dining_room: '餐廳',
  living_dining: '客餐廳', bathroom: '衛浴', balcony: '陽台',
}

// roomplan 的房型字彙（見 designbridge/roomplan/constants.py ROOM_TYPE_SPECS）→
// LayoutEditor 家具面板/scene_graph 用的字彙（見 frontend/src/config/furniture.js）。
// bedroom_master 沒有獨立家具面板，主臥跟一般臥室家具需求相同，直接併入 bedroom。
const CAD_ROOM_TYPE_TO_EDITOR = {
  bedroom_master: 'bedroom',
  bedroom: 'bedroom',
  living_dining: 'living_dining',
  kitchen: 'kitchen',
  bathroom: 'bathroom',
  balcony: 'balcony',
}

// 選完房間後的預設家具擺法——跟 layout_agent.py 的 _default_layout 同一種做法
// （靜態的歸一化座標 preset，不是 AI 排的），純前端、選完房間立刻有東西可看/可調，
// 不用等一次 LLM 呼叫。之所以不直接呼叫 /api/generate-layout 讓 AI 排版：那個端點
// 背後的 _normalize_ftype 只認得 FURNITURE_SIZES 裡的字彙（沙發、床…），bathtub／
// washer 這些新家具類型不在裡面，LLM 排出來也會被當成未知類型整個丟掉（見
// layout_agent.py 的 _call_llm_layout），排版一定失敗、退回 living_room 預設，
// 對衛浴／陽台反而是錯的結果。
const CAD_DEFAULT_LAYOUT = {
  bedroom: [
    { type: 'bed', x: 0.30, y: 0.28, w: 0.22, h: 0.28 },
    { type: 'wardrobe', x: 0.08, y: 0.08, w: 0.18, h: 0.08 },
    { type: 'nightstand', x: 0.24, y: 0.58, w: 0.07, h: 0.07 },
  ],
  living_dining: [
    { type: 'sofa', x: 0.08, y: 0.55, w: 0.30, h: 0.13 },
    { type: 'coffee_table', x: 0.16, y: 0.42, w: 0.15, h: 0.10 },
    { type: 'tv_unit', x: 0.08, y: 0.08, w: 0.22, h: 0.07 },
    { type: 'dining_table', x: 0.58, y: 0.55, w: 0.20, h: 0.15 },
    { type: 'chair', x: 0.58, y: 0.42, w: 0.08, h: 0.08 },
    { type: 'chair', x: 0.68, y: 0.42, w: 0.08, h: 0.08 },
    { type: 'chair', x: 0.58, y: 0.72, w: 0.08, h: 0.08 },
    { type: 'chair', x: 0.68, y: 0.72, w: 0.08, h: 0.08 },
  ],
  kitchen: [
    { type: 'cabinet', x: 0.05, y: 0.05, w: 0.30, h: 0.08 },
    { type: 'shelf', x: 0.60, y: 0.05, w: 0.18, h: 0.05 },
  ],
  bathroom: [
    { type: 'bathtub', x: 0.05, y: 0.05, w: 0.30, h: 0.14 },
    { type: 'sink', x: 0.60, y: 0.10, w: 0.10, h: 0.08 },
    { type: 'toilet', x: 0.60, y: 0.60, w: 0.09, h: 0.12 },
  ],
  balcony: [
    { type: 'washer', x: 0.08, y: 0.08, w: 0.16, h: 0.16 },
    { type: 'drying_rack', x: 0.40, y: 0.10, w: 0.20, h: 0.06 },
  ],
}

function cadDefaultPlacements(editorRoomType) {
  const seen = {}
  return (CAD_DEFAULT_LAYOUT[editorRoomType] || []).map((f) => {
    seen[f.type] = (seen[f.type] || 0) + 1
    return { id: `${f.type}_${seen[f.type]}`, type: f.type, x: f.x, y: f.y, w: f.w, h: f.h, rotation: 0 }
  })
}

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
const uploadedPlanPath  = ref('')   // 原始（未裁切）上傳圖的本機路徑，選房間裁切時要用
const detectedRooms     = ref([])   // /api/detect-rooms 偵測到的房間清單，多間時才會用到

// ── CAD 房型生成（designbridge/roomplan）──
const cadCounts     = ref({ bedroom_count: 2, living_count: 1, bathroom_count: 1, kitchen_count: 1, balcony_count: 1 })
const cadTotalPing  = ref(32)        // 2房1廳1衛1廚1陽台在 25 坪下房間偏小，32 坪落地起來更合理
const cadPlanResult = ref(null)     // /api/generate-room-plan 的完整回應（rooms/walls/doors/windows/svg_markup…）

// ── CAD 多房間逐一設計：進度追蹤（右上角縮圖用）──
// 一次只「啟用」一間房：房間必須渲染出 3D 圖才算完成，完成前縮圖不能點去別間房
// （使用者的決定）。cadRoomSnapshots 存每間房各自的家具/平面圖/渲染結果，離開時存檔、
// 回來時還原，這樣同一間房不會因為切去別間又切回來而遺失進度。
const cadActiveRoomId  = ref(null)          // 目前正在設計的房間 id
const cadRoomStatus    = ref({})            // { [roomId]: 'active' | 'done' }
const cadRoomSnapshots = ref({})            // { [roomId]: { roomW, roomD, roomTypeForPlan, editPlacements, floorPlanPath, floorPlanUrl, sceneGraph, layoutRenderConfig, result, lastGeneratedImage } }

// ── 佈局編輯 ──
const editPlacements     = ref([])
const roomW              = ref(5.0)
const roomD              = ref(4.0)
const roomTypeForPlan    = ref('living_room')
const layoutViewMode     = ref('2d')        // '2d' | '3d'
const layoutRenderConfig = ref(null)

// ── 空間設定表單 ──
const roomType       = ref('living_room')
const spaceSizePing  = ref(8)        // 4 坪對單一房間（含客廳預設）太擠，8 坪是比較合理的起始值
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
const brushSize          = ref(32)   // 畫筆直徑（px）
const eraserSize         = ref(32)   // 橡皮擦直徑（px）——獨立於畫筆，兩個工具可以各自調大小
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
  uploadedPlanPath.value = ''
  detectedRooms.value = []
  cadPlanResult.value = null
  cadActiveRoomId.value = null
  cadRoomStatus.value = {}
  cadRoomSnapshots.value = {}
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

/* ══ Step: 上傳 2D 平面配置圖 ═══════════════════════════════
   整戶圖（多房間）會先經過「選擇房間」再解析；單一房間圖直接跳過那一步，
   行為等同直接解析整張圖——沿用舊 HomeView.vue 驗證過的三段式寫法。 */

async function useUploadedPlan() {
  if (!floorPlanUpload.file) {
    error.value = '請先上傳平面配置圖'
    return
  }
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '上傳平面圖中', sub: '處理你的平面配置圖' }
  result.value = null
  try {
    const path = await uploadFile(floorPlanUpload.file)
    if (requestId !== currentRequestId) return
    uploadedPlanUrl.value = mediaUrl(path)
    uploadedPlanPath.value = path

    // 先看看這張圖是不是含多個房間（整戶圖）——是的話讓使用者先選一間，
    // 免得所有房間的家具被混進同一個矩形房間框裡。
    let rooms = []
    try {
      const roomsRes = await fetch(apiUrl('/api/detect-rooms'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_path: path }),
      })
      if (roomsRes.ok) rooms = (await roomsRes.json()).rooms || []
    } catch {
      rooms = [] // 偵測失敗就當單一房間處理，不擋住原本的流程
    }
    if (requestId !== currentRequestId) return

    if (rooms.length > 1) {
      detectedRooms.value = rooms
      loading.value = false
      nextStep() // → 'roomPick'
      return
    }

    await parseFloorPlanAndProceed(path, requestId, rooms[0]?.room_type)
  } catch (e) {
    if (requestId === currentRequestId) error.value = `解析平面圖失敗：${e.message}`
    if (requestId === currentRequestId) loading.value = false
  }
}

// ── 使用者從「選擇房間」步驟選定房間後裁切 + 解析 ──
async function handleRoomSelected(room) {
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '裁切房間中', sub: '準備該房間的平面圖' }
  try {
    const res = await fetch(apiUrl('/api/crop-floor-plan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_path: uploadedPlanPath.value,
        x: room.x, y: room.y, w: room.w, h: room.h,
      }),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const { path: croppedPath } = await res.json()
    if (requestId !== currentRequestId) return
    uploadedPlanUrl.value = mediaUrl(croppedPath)

    await parseFloorPlanAndProceed(croppedPath, requestId, room.room_type)
  } catch (e) {
    if (requestId === currentRequestId) error.value = `裁切房間失敗：${e.message}`
    if (requestId === currentRequestId) loading.value = false
  }
}

// 呼叫 /api/parse-floor-plan → 塞進可編輯的 scene_graph → 進「繪製平面圖」步驟。
// 用 goStep(絕對 index) 而不是 nextStep()，因為這個函式在「有無先經過選房間」
// 兩種路徑下都會被呼叫，呼叫當下的 stepIndex 不一樣。
async function parseFloorPlanAndProceed(path, requestId, roomTypeOverride) {
  loading.value = true
  loadingMsg.value = { title: '解析平面圖中', sub: 'AI 辨識平面圖上的家具配置' }
  try {
    const res = await fetch(apiUrl('/api/parse-floor-plan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_path: path,
        room_type: roomTypeOverride || roomType.value,
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
    roomTypeForPlan.value = data.room_type || roomTypeOverride || roomType.value
    goStep(steps.value.findIndex(s => s.key === 'plan'))
    if (extraPrompt.value.trim()) scheduleSearch()
  } catch (e) {
    if (requestId === currentRequestId) error.value = `解析平面圖失敗：${e.message}`
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

/* ══ Step: CAD 房型生成 ═══════════════════════════════════
   輸入幾房幾廳＋總坪數 → /api/generate-room-plan 直接切割出整層樓的房間配置
   （牆／門／窗，結構化資料，不需要再像上傳流程那樣用 Gemini 視覺辨識），一定是
   多房間，所以固定進「選擇房間」步驟，使用者選一間後才落地成單房間的
   scene_graph 交給既有的 LayoutEditor。 */

async function submitRoomProgram() {
  const requestId = ++currentRequestId
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '生成房型配置中', sub: '依房型配置切割空間、繪製牆體與門窗' }
  result.value = null
  try {
    const res = await fetch(apiUrl('/api/generate-room-plan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...cadCounts.value, total_ping: cadTotalPing.value }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || `${res.status}`)
    if (requestId !== currentRequestId) return
    cadPlanResult.value = data
    if ((data.rooms || []).length > 1) {
      loading.value = false
      nextStep() // → 'roomPick'
      return
    }
    if (data.rooms?.[0]) await handleCadRoomSelected(data.rooms[0], requestId)
    else { error.value = '沒有可用的房間，請調整房型配置'; loading.value = false }
  } catch (e) {
    if (requestId === currentRequestId) { error.value = `生成房型配置失敗：${e.message}`; loading.value = false }
  }
}

// 把目前這間房相關的狀態存一份快照，供之後從縮圖切回來還原用。
function snapshotCurrentCadRoom() {
  const id = cadActiveRoomId.value
  if (!id) return
  cadRoomSnapshots.value = {
    ...cadRoomSnapshots.value,
    [id]: {
      roomW: roomW.value, roomD: roomD.value, roomTypeForPlan: roomTypeForPlan.value,
      editPlacements: editPlacements.value, floorPlanPath: floorPlanPath.value, floorPlanUrl: floorPlanUrl.value,
      sceneGraph: sceneGraph.value, layoutRenderConfig: layoutRenderConfig.value,
      result: result.value, lastGeneratedImage: lastGeneratedImage.value,
    },
  }
}

function restoreCadRoomSnapshot(roomId) {
  const snap = cadRoomSnapshots.value[roomId]
  if (!snap) return false
  roomW.value = snap.roomW
  roomD.value = snap.roomD
  roomTypeForPlan.value = snap.roomTypeForPlan
  editPlacements.value = snap.editPlacements
  floorPlanPath.value = snap.floorPlanPath
  floorPlanUrl.value = snap.floorPlanUrl
  sceneGraph.value = snap.sceneGraph
  layoutRenderConfig.value = snap.layoutRenderConfig
  result.value = snap.result
  lastGeneratedImage.value = snap.lastGeneratedImage
  return true
}

// 使用者從「選擇房間」／右上角縮圖選定一間房後，把它的絕對座標矩形換算成單房間的
// roomW/roomD。回頭選過的房間（cadRoomSnapshots 裡已經有）直接還原上次的進度；
// 第一次選的房間才用 cadDefaultPlacements 的預設家具跟 render-floor-plan 要一張底圖。
async function handleCadRoomSelected(room, requestId = ++currentRequestId) {
  cadActiveRoomId.value = room.id
  if (!cadRoomStatus.value[room.id]) {
    cadRoomStatus.value = { ...cadRoomStatus.value, [room.id]: 'active' }
  }
  uploadedPlanUrl.value = cadPlanResult.value?.svg_url || ''

  if (restoreCadRoomSnapshot(room.id)) {
    goStep(steps.value.findIndex(s => s.key === 'plan'))
    return
  }

  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '準備房間底圖中', sub: '生成預設家具配置與平面圖' }
  try {
    roomW.value = room.w
    roomD.value = room.h
    roomTypeForPlan.value = CAD_ROOM_TYPE_TO_EDITOR[room.room_type] || 'living_room'
    sceneGraph.value = null
    editPlacements.value = cadDefaultPlacements(roomTypeForPlan.value)

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
    if (requestId !== currentRequestId) return
    floorPlanPath.value = data.floor_plan_path || ''
    floorPlanUrl.value = data.floor_plan_url || ''
    goStep(steps.value.findIndex(s => s.key === 'plan'))
  } catch (e) {
    if (requestId === currentRequestId) error.value = `準備房間底圖失敗：${e.message}`
  } finally {
    if (requestId === currentRequestId) loading.value = false
  }
}

// 縮圖上點別間房——只有目前這間已經渲染完成（cadRoomStatus === 'done'）才會被呼叫
// （縮圖元件自己也擋，這裡再擋一次避免中途跳房弄亂進度）。
function jumpToCadRoom(room) {
  const activeId = cadActiveRoomId.value
  if (activeId && cadRoomStatus.value[activeId] !== 'done') return
  if (room.id === activeId) return
  snapshotCurrentCadRoom()
  handleCadRoomSelected(room)
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
      // CAD 多房間流程：這間房的 3D 渲染圖生成完成才算「完成」，縮圖到這裡才會解鎖、
      // 可以點去別間房（見 jumpToCadRoom）。
      if (planSource.value === 'cad' && cadActiveRoomId.value) {
        cadRoomStatus.value = { ...cadRoomStatus.value, [cadActiveRoomId.value]: 'done' }
        snapshotCurrentCadRoom()
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
      // 微調也是同一間房的最新結果，重新存一次快照，回來看到的才是微調後的版本
      if (planSource.value === 'cad' && cadActiveRoomId.value) snapshotCurrentCadRoom()
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
    detectedRooms, handleRoomSelected,
    // CAD 房型生成
    cadCounts, cadTotalPing, cadPlanResult, submitRoomProgram, handleCadRoomSelected,
    cadActiveRoomId, cadRoomStatus, jumpToCadRoom,
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
    spaceImage, lastGeneratedImage, manualMaskPath, brushSize, eraserSize, drawMode, editScope,
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
