import { ref, computed } from 'vue'
import { useImageField } from '@/composables/useImageField'

/**
 * 整條設計流程共用的模組層級狀態。
 *
 * 為什麼是「模組層級單例」而不是每次呼叫都建一份：新版 UI 是線性精靈，每一步都是
 * 獨立元件，切步驟時前一個元件會被卸載。狀態放在模組層級，切步驟（甚至跑去個人專區
 * 再回來）都不會掉資料——這是舊版把全部狀態塞在 HomeView 裡時「免費」得到的性質，
 * 拆成多個元件後必須自己維持。
 *
 * 這個檔案只放狀態本身；依狀態運作的邏輯依 domain 拆到同目錄的其他檔案，
 * 最後由 ../useDesignFlow.js 組裝、對外暴露同一份 API。
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

export const STYLE_PAGE_SIZE = 10
export const ROOM_TYPE_LABEL = {
  living_room: '客廳', bedroom: '臥室', kitchen: '廚房', study: '書房', dining_room: '餐廳',
  living_dining: '客餐廳', bathroom: '衛浴', balcony: '陽台',
}

// roomplan 的房型字彙（見 designbridge/roomplan/constants.py ROOM_TYPE_SPECS）→
// LayoutEditor 家具面板/scene_graph 用的字彙（見 frontend/src/config/furniture.js）。
// bedroom_master 沒有獨立家具面板，主臥跟一般臥室家具需求相同，直接併入 bedroom。
export const CAD_ROOM_TYPE_TO_EDITOR = {
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

export function cadDefaultPlacements(editorRoomType) {
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
export const planSource = ref('generate')          // 'generate' | 'photo' | 'skip' | 'upload'
export const stepIndex  = ref(0)

// ── 平面圖 ──
export const floorPlanUrl      = ref('')
export const floorPlanPath     = ref('')
export const sceneGraph        = ref(null)
export const floorPlanUpload   = useImageField()
export const uploadedPlanUrl   = ref('')
export const uploadedPlanPath  = ref('')   // 原始（未裁切）上傳圖的本機路徑，選房間裁切時要用
export const detectedRooms     = ref([])   // /api/detect-rooms 偵測到的房間清單，多間時才會用到

// ── CAD 房型生成（designbridge/roomplan）──
export const cadCounts     = ref({ bedroom_count: 2, living_count: 1, bathroom_count: 1, kitchen_count: 1, balcony_count: 1 })
export const cadTotalPing  = ref(32)        // 2房1廳1衛1廚1陽台在 25 坪下房間偏小，32 坪落地起來更合理
export const cadPlanResult = ref(null)     // /api/generate-room-plan 的完整回應（rooms/walls/doors/windows/svg_markup…）

// ── CAD 多房間逐一設計：進度追蹤（右上角縮圖用）──
// 一次只「啟用」一間房：房間必須渲染出 3D 圖才算完成，完成前縮圖不能點去別間房
// （使用者的決定）。cadRoomSnapshots 存每間房各自的家具/平面圖/渲染結果，離開時存檔、
// 回來時還原，這樣同一間房不會因為切去別間又切回來而遺失進度。
export const cadActiveRoomId  = ref(null)          // 目前正在設計的房間 id
export const cadRoomStatus    = ref({})            // { [roomId]: 'active' | 'done' }
export const cadRoomSnapshots = ref({})            // { [roomId]: { roomW, roomD, roomTypeForPlan, editPlacements, floorPlanPath, floorPlanUrl, sceneGraph, layoutRenderConfig, result, lastGeneratedImage } }

// ── 佈局編輯 ──
export const editPlacements     = ref([])
export const roomW              = ref(5.0)
export const roomD              = ref(4.0)
export const roomTypeForPlan    = ref('living_room')
export const layoutViewMode     = ref('2d')        // '2d' | '3d'
export const layoutRenderConfig = ref(null)

// ── 空間設定表單 ──
export const roomType       = ref('living_room')
export const spaceSizePing  = ref(8)        // 4 坪對單一房間（含客廳預設）太擠，8 坪是比較合理的起始值
export const customRoomW    = ref(null)            // 公尺，null = 用坪數估算
export const customRoomD    = ref(null)
export const furnitureItems = ref([])
export const furnitureQty   = ref({})
export const extraPrompt    = ref('')
export const familyNeeds    = ref([])
export const fengshuiRules  = ref([])
export const outputAspect   = ref('auto')

// ── 空間照片（上傳照片入口）──
export const spacePhoto     = useImageField()
export const spacePhotoPath = ref('')

// ── 風格 ──
export const selectedStyle       = ref('auto')
export const noStyleReference    = ref(false)
export const styleMethod         = ref('ai_analysis')
export const styleRefImage       = useImageField()
export const styleOptions        = ref([{ label: '自動', value: 'auto' }])
export const styleLoading        = ref(false)
export const styleError          = ref('')
export const styleCandidates     = ref([])
export const styleCandidatePool  = ref([])
export const candidatesLoading   = ref(false)
export const candidatesSearched  = ref(false)
export const confirmedStyle      = ref(null)
export const matchedStylePreview = ref(null)
export const styleDemoImages     = ref({})  // { [style_id]: image_url } —— 一鍵換風格還沒生成過的卡片先顯示這張示範圖

// ── 結果 ──
export const result        = ref(null)
export const loading       = ref(false)
export const loadingMsg    = ref({ title: '', sub: '' })
export const error         = ref('')
export const submitKey     = ref(0)
export const swappingStyle = ref(false)  // 一鍵換風格：只重跑 style 搜尋 + render，不吃 loading/loadingMsg 那套全頁 overlay
export const styleSwapCache = ref({})    // { [style_profile_id]: 該風格上次生成的完整 /api/generate 回應 } —— 換回去不用重打

// 跨 domain 共用的請求序號／計時器，用物件包起來而不是裸 let——
// ES module 匯出的裸 let 綁定在其他檔案裡是唯讀的，物件屬性可以互相寫入。
export const requestState = { current: 0 }
export const timers = { search: null, floorPlanUpdate: null }

// ── 微調 ──
export const spaceImage         = useImageField()
export const lastGeneratedImage = ref(null)
export const manualMaskPath     = ref('')
export const brushSize          = ref(32)   // 畫筆直徑（px）
export const eraserSize          = ref(32)   // 橡皮擦直徑（px）——獨立於畫筆，兩個工具可以各自調大小
export const drawMode           = ref('draw')
export const textPrompt         = ref('')
export const refineCanvasRef    = ref(null)

// ── 360° 環景（原本在 ResultPanel，設計稿拆成獨立步驟）──
export const panoLoading = ref(false)
export const panoUrl     = ref(null)
export const panoError   = ref('')

// ── 家具估價（原本在 ResultPanel）──
export const quotationLoading = ref(false)
export const quotationError   = ref('')

// ── 收藏這個設計（預算估計步驟最後一顆按鈕）──
// 每次 /api/generate 都已經自動存進 artifacts/history.json 了，收藏不是另開一份
// 清單，只是在同一筆紀錄上標記 favorited=true，讓它在歷史紀錄裡好找、不會被
// 使用者自己在歷史紀錄頁批次刪除時誤刪。
export const favoriteLoading = ref(false)
export const favoriteError   = ref('')

/* ══ 衍生值 ══════════════════════════════════════════════ */

export const steps        = computed(() => STEP_FLOWS[planSource.value] || STEP_FLOWS.generate)
export const currentStep  = computed(() => steps.value[stepIndex.value]?.key || 'space')
export const isLastStep   = computed(() => stepIndex.value >= steps.value.length - 1)

export const baseImagePreview = computed(
  () => lastGeneratedImage.value?.url || spaceImage.preview || spacePhoto.preview || null,
)

export const showSuggestions = computed(
  () => !styleRefImage.file &&
    (styleCandidates.value.length > 0 || candidatesLoading.value || candidatesSearched.value),
)
