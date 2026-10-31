import { ref, computed, watch } from 'vue'
import { useImageField } from '@/composables/useImageField'
import { buildRoomGeometry, doorKeepouts, settlePlacements } from '@/utils/roomGeometry'
import { furnitureRealSize } from '@/config/furniture'

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
    { key: 'result', label: '生成設計' },
  ],
  // 上傳現有空間照片
  photo: [
    { key: 'photo',  label: '空間照片上傳' },
    { key: 'result', label: '生成設計' },
  ],
  // 從零開始，直接描述理想空間
  skip: [
    { key: 'space',  label: '空間設定' },
    { key: 'result', label: '生成設計' },
  ],
  // 上傳 2D 平面配置圖。整戶圖會先用 Gemini 視覺分割房間，偵測到多間才會經過
  // 「選擇房間」這一步；只有一間就直接跳過，行為等同單純上傳一張房間圖。
  upload: [
    { key: 'planUpload', label: '上傳平面圖' },
    { key: 'roomPick',   label: '選擇房間' },
    { key: 'plan',       label: '繪製平面圖' },
    { key: 'result',     label: '生成設計' },
  ],
  // CAD 房型生成（designbridge/roomplan）：輸入幾房幾廳＋總坪數，直接切割出整層樓
  // 的房間配置（牆／門／窗）。一定是多房間，但「填房型」跟「選房間」合併成同一頁
  // （見 StepRoomProgram）：生成配置後房間選擇器直接在表單下方展開，不用再跳頁。
  cad: [
    { key: 'roomProgram', label: '房型設定' },
    { key: 'plan',        label: '繪製平面圖' },
    { key: 'result',      label: '生成設計' },
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
  dining: 'living_dining',
  kitchen: 'kitchen',
  bathroom: 'bathroom',
  balcony: 'balcony',
  // 上傳平面圖切出的房間（floorplan_upload_plan.py）直接用編輯器字彙；認不出的空間給中性的
  // room，家具面板退回預設清單
  living_room: 'living_room',
  dining_room: 'dining_room',
  study: 'study',
  other: 'room',
}

// 選完房間後的預設家具擺法——跟 layout_agent.py 的 _default_layout 同一種做法
// （靜態的歸一化座標 preset，不是 AI 排的），純前端、選完房間立刻有東西可看/可調，
// 不用等一次 LLM 呼叫。之所以不直接呼叫 /api/generate-layout 讓 AI 排版：那個端點
// 背後的 _normalize_ftype 只認得 FURNITURE_SIZES 裡的字彙（沙發、床…），bathtub／
// washer 這些新家具類型不在裡面，LLM 排出來也會被當成未知類型整個丟掉（見
// layout_agent.py 的 _call_llm_layout），排版一定失敗、退回 living_room 預設，
// 對衛浴／陽台反而是錯的結果。
// 每種房型一個 builder：用公尺貼牆擺（真實家具尺寸，見 config/furniture.js），再換成歸一化座標。
// 門／窗位置沒有納入考量——開門範圍內預設就有家具也沒關係，編輯器允許把它拖出來（見 LayoutEditor 的 doorKeepouts）。
// 客廳預設擺法（家具中心點，佔客廳區域寬深的比例）：電視櫃靠上、沙發在下方正對電視，
// 茶几居中，扶手椅在左、邊桌靠右。尺寸用真實尺寸，房間大小不同時家具不會被拉伸。
// 順序即優先度：小房間擺不下時 settlePlacements 會挪動後面的，所以次要家具放後面
const LIVING_ROOM_PRESET = [
  ['sofa', 0.49, 0.79], ['tv_unit', 0.45, 0.18], ['coffee_table', 0.49, 0.47],
  ['side_table', 0.94, 0.64], ['armchair', 0.12, 0.51], ['plant', 0.61, 0.05],
]
function putLivingRoom(put, zoneX, zoneW, D) {
  for (const [type, cx, cy] of LIVING_ROOM_PRESET) {
    const [rw, rd] = furnitureRealSize(type)
    put(type, zoneX + cx * zoneW - rw / 2, cy * D - rd / 2)
  }
}

const CAD_DEFAULT_LAYOUT = {
  // 上傳平面圖點進客廳、卻沒辨識到家具時也用這份（見 layout.js parseFloorPlanAndProceed）
  living_room: (W, D, put) => putLivingRoom(put, 0, W, D),
  bedroom: (W, D, put) => {
    const bx = (W - 1.5) / 2
    put('bed', bx, 0.05)                         // 床頭靠上牆、置中
    put('nightstand', bx - 0.5, 0.05)
    put('nightstand', bx + 1.55, 0.05)
    put('wardrobe', 0.05, D - 0.65)              // 衣櫃靠下牆
  },
  dining_room: (W, D, put) => {
    const cx = W / 2, cy = D / 2
    put('dining_table', cx - 0.7, cy - 0.4)
    put('chair', cx - 0.55, cy - 0.9)
    put('chair', cx + 0.1, cy - 0.9)
    put('chair', cx - 0.55, cy + 0.45)
    put('chair', cx + 0.1, cy + 0.45)
  },
  living_dining: (W, D, put) => {
    if (W * D < 18) {                            // 單獨的餐廳（客餐廳合一的房間都比這大）：只擺餐桌椅
      const cx = W / 2, cy = D / 2
      put('dining_table', cx - 0.7, cy - 0.4)
      put('chair', cx - 0.55, cy - 0.9)
      put('chair', cx + 0.1, cy - 0.9)
      put('chair', cx - 0.55, cy + 0.45)
      put('chair', cx + 0.1, cy + 0.45)
      return
    }
    const dx = W * 0.78                          // 客廳在左 55%、餐廳在右
    putLivingRoom(put, 0, W * 0.55, D)
    put('dining_table', dx - 0.7, D / 2 - 0.4)
    put('chair', dx - 0.55, D / 2 - 0.9)
    put('chair', dx + 0.1, D / 2 - 0.9)
    put('chair', dx - 0.55, D / 2 + 0.45)
    put('chair', dx + 0.1, D / 2 + 0.45)
  },
  kitchen: (W, D, put) => {
    put('cabinet', 0.05, 0.05, 2.4, 0.6)         // 流理台沿上牆
    put('shelf', 0.05, D - 0.35)
  },
  bathroom: (W, D, put) => {
    put('bathtub', 0.05, 0.05)
    put('sink', 0.05, D - 0.5)
    put('toilet', W - 0.45, D - 0.75)
  },
  balcony: (W, D, put) => {
    put('washer', 0.05, 0.05)
    put('drying_rack', Math.max(0.05, (W - 1.2) / 2), Math.min(2.0, D - 0.5))
  },
}

export function cadDefaultPlacements(editorRoomType, roomW = 5, roomD = 4, geometry = null) {
  const build = CAD_DEFAULT_LAYOUT[editorRoomType]
  if (!build) return []
  const out = [], seen = {}
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
  // 牆沿房間矩形（牆中心線）往內畫一半厚度；家具要在牆的內緣以內，不然會跟牆疊在一起
  const wt = geometry?.wallT || {}
  const x0 = (wt.left || 0) / 2 / roomW, x1 = 1 - (wt.right || 0) / 2 / roomW
  const y0 = (wt.top || 0) / 2 / roomD, y1 = 1 - (wt.bottom || 0) / 2 / roomD
  const put = (type, xm, ym, wm, dm) => {
    const [rw, rd] = furnitureRealSize(type)
    const w = clamp((wm ?? rw) / roomW, 0.04, 0.9), h = clamp((dm ?? rd) / roomD, 0.04, 0.9)
    seen[type] = (seen[type] || 0) + 1
    out.push({
      id: `${type}_${seen[type]}`, type, rotation: 0, w, h,
      x: clamp(xm / roomW, x0, Math.max(x0, x1 - w)), y: clamp(ym / roomD, y0, Math.max(y0, y1 - h)),
    })
  }
  build(roomW, roomD, put)
  // 門會碰到的範圍不擺家具
  return settlePlacements(
    out,
    doorKeepouts(geometry, roomW, roomD),
    { x0, x1, y0, y1 },
  )
}

export const ASPECT_OPTIONS = [
  { value: 'auto', label: '自動' },
  { value: '1:1',  label: '1:1 正方形' },
  { value: '4:3',  label: '4:3 橫式' },
  { value: '3:4',  label: '3:4 直式' },
  { value: '16:9', label: '16:9 寬螢幕' },
  { value: '9:16', label: '9:16 直式寬螢幕' },
]
// 風水規則選單。每一筆都要對得上 skills/constraints/<slug>/SKILL.md 的 `trigger`，
// 對不上就是「勾了沒作用」——test/test_fengshui_constraints.py 會把兩邊比對起來擋下來。
//   · desc  ：chip 上直接顯示的一句話，使用者不必猜「開門不見灶」是什麼意思
//   · rooms ：跟目前房型相關的規則排在前面，其餘收進「其他空間的規則」
//   · fix   ：勾了之後排版實際會做的事，寫給會追問「所以它會怎麼改」的人
//   · group ：對應 SKILL.md 的 category，細調清單依此分組（FENGSHUI_GROUPS）
export const FENGSHUI_OPTIONS = [
  {
    value: 'door_not_facing_bed', group: 'door', label: '開門不見床', icon: 'mdi:door-open',
    desc: '整張床都不落在門口的正向視線上',
    fix: '床整個推出門的視線帶',
    rooms: ['bedroom', 'kids_room'],
  },
  {
    value: 'bed_head_not_under_window', group: 'backing', label: '床頭不靠窗', icon: 'mdi:window-closed-variant',
    desc: '床頭要靠實牆，不睡在窗戶底下',
    fix: '床沿著同一面牆滑到沒有開窗的那一段',
    rooms: ['bedroom', 'kids_room'],
  },
  {
    value: 'mirror_not_facing_bed', group: 'reflect', label: '鏡不照床', icon: 'mdi:mirror',
    desc: '鏡面不正對睡床，睡醒不會照到自己',
    fix: '移動的是床——鏡子掛在牆上，換牆等於換裝潢',
    rooms: ['bedroom', 'kids_room'],
  },
  {
    value: 'door_not_facing_mirror', group: 'reflect', label: '門不對鏡', icon: 'mdi:mirror-rectangle',
    desc: '一進門不被鏡面正對回照',
    fix: '鏡子挪出門的正向視線帶',
    rooms: ['bedroom', 'living_room', 'bathroom'],
  },
  {
    value: 'sofa_not_back_to_window', group: 'backing', label: '沙發不背窗', icon: 'mdi:sofa-outline',
    desc: '沙發背後要有靠，不背對整片落地窗',
    fix: '沙發沿著牆滑到實牆段',
    rooms: ['living_room', 'living_dining'],
  },
  {
    value: 'desk_not_back_to_door', group: 'backing', label: '書桌不背門', icon: 'mdi:desk',
    desc: '坐著的時候能側身看到門口',
    fix: '書桌沿牆推開，座位不再正背著門',
    rooms: ['study', 'bedroom', 'kids_room'],
  },
  {
    value: 'desk_not_facing_window', group: 'reflect', label: '書桌不正對窗', icon: 'mdi:desk-lamp',
    desc: '側對窗戶取自然側光，避免正面眩光',
    fix: '書桌往室內推離窗戶中心線',
    rooms: ['study', 'bedroom', 'kids_room'],
  },
  {
    value: 'door_not_facing_stove', group: 'door', label: '開門不見灶', icon: 'mdi:stove',
    desc: '站在廚房門口看不到爐灶',
    fix: '爐灶橫向推出門的視線帶',
    rooms: ['kitchen'],
  },
  {
    value: 'stove_not_under_window', group: 'backing', label: '灶後不宜空', icon: 'mdi:fire',
    desc: '爐灶背後是實牆，不背對窗戶',
    fix: '爐灶沿著流理檯那面牆滑到實牆段',
    rooms: ['kitchen'],
  },
  {
    value: 'stove_away_from_water', group: 'kitchen', label: '水火不相容', icon: 'mdi:water-off',
    desc: '爐灶與水槽、冰箱之間留出備料檯面',
    fix: '兩者互相推開至少 60 公分',
    rooms: ['kitchen'],
  },
  {
    value: 'door_not_facing_toilet', group: 'door', label: '開門不見廁', icon: 'mdi:toilet',
    desc: '馬桶不正對浴室門口',
    fix: '馬桶橫向推出門的視線帶',
    rooms: ['bathroom'],
  },
  {
    value: 'door_not_facing_window', group: 'door', label: '穿堂煞', icon: 'mdi:weather-windy',
    desc: '門正對對牆的窗，一進門氣就直穿出去',
    fix: '把一件高櫃／書架搬到門窗之間當屏風',
    rooms: ['living_room', 'living_dining', 'bedroom', 'study', 'kitchen', 'bathroom', 'kids_room'],
  },
]

// 14 條規則收成四個原則，使用者只需要懂這四個詞
export const FENGSHUI_GROUPS = [
  { key: 'door',    label: '門口沖煞',   desc: '床、爐灶、馬桶不正對門口，門窗不成一直線' },
  { key: 'backing', label: '背後有靠',   desc: '床頭、沙發、爐灶、座位背後是實牆' },
  { key: 'reflect', label: '鏡面與光線', desc: '鏡子不照床、不對門，書桌避開正面眩光' },
  { key: 'kitchen', label: '水火分離',   desc: '爐灶與水槽、冰箱之間留出檯面' },
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
// 平面圖解析沒結果時停下來讓使用者決定，不默默退回後備路徑：
// { kind: 'rooms' | 'furniture', reason: 'failed' | 'empty', path, roomType }
export const planParseIssue    = ref(null)

// ── CAD 房型生成（designbridge/roomplan）──
export const cadCounts     = ref({ bedroom_count: 2, living_count: 1, dining_count: 1, bathroom_count: 1, kitchen_count: 1, balcony_count: 1 })
export const cadExtraRooms = ref([])   // 自訂空間名稱（書房、儲藏室…），每個 1 間
export const cadTotalPing  = ref(32)        // 2房1廳1衛1廚1陽台在 25 坪下房間偏小，32 坪落地起來更合理
export const cadRoomW      = ref(null)      // 整層外框寬／深（公尺）；跟總坪數連動，null＝還沒算過（由坪數推出）
export const cadRoomD      = ref(null)
export const cadPlanResult = ref(null)     // /api/generate-room-plan 的完整回應（rooms/walls/doors/windows/svg_markup…）

// ── CAD 多房間逐一設計：進度追蹤（右上角縮圖用）──
// 一次只「啟用」一間房：房間必須渲染出 3D 圖才算完成，完成前縮圖不能點去別間房
// （使用者的決定）。cadRoomSnapshots 存每間房各自的家具/平面圖/渲染結果，離開時存檔、
// 回來時還原，這樣同一間房不會因為切去別間又切回來而遺失進度。
export const cadActiveRoomId  = ref(null)          // 目前正在設計的房間 id
export const cadRoomStatus    = ref({})            // { [roomId]: 'active' | 'done' }
// 正在渲染的房間（{ [roomId]: true }）。渲染要 30–60 秒，這段時間可以切去看別間，
// 所以它不是全域的 loading，而是每間房各自的背景工作；結果回來時依使用者人在哪間決定放哪裡（見 render.js）。
export const cadRendering     = ref({})
export const cadRenderError   = ref({})            // 使用者離開後才失敗的渲染：{ [roomId]: 錯誤訊息 }，回到那間房時再顯示
// 每間房各自的渲染編號（非響應式）：同一間房重新送出、或整層重新生成時，舊的那次回來要作廢。
// 不能用全域的 requestState——切房間會遞增它，等於把還在跑的渲染宣告作廢。
export const cadRenderTokens  = {}
// 目前這間房的牆厚／門／窗（從整層結果換算，不另外存——快照還原也會自動對上）。非 CAD 路徑沒有資料就是 null。
// 使用者拖動／改寬度後的門窗：{ 'roomId:openingId': { frac?, width? } }，疊在換算結果上。共用的內門在兩間房各自記一份。
export const openingEdits = ref({})
export const roomGeometry = computed(() => {
  if (planSource.value !== 'cad' || !cadActiveRoomId.value) return null
  const room = cadPlanResult.value?.rooms?.find(r => r.id === cadActiveRoomId.value)
  const g = buildRoomGeometry(room, cadPlanResult.value)
  if (!g) return null
  return { ...g, openings: g.openings.map(o => ({ ...o, ...openingEdits.value[`${room.id}:${o.id}`] })) }
})
// 「我的設計」的分組：一次精靈流程 = 一個設計（project），整層 CAD 的每間房是它的一個空間
export const projectId = ref(crypto.randomUUID())
// 整層 CAD 平面圖（含牆／門／窗／尺寸）連同使用者改過的門窗一起存；SVG 本體由後端依 svg_path 上傳
export function cadPlanPayload() {
  if (!cadPlanResult.value) return undefined
  const { svg_markup, ...plan } = cadPlanResult.value
  return { ...plan, opening_edits: openingEdits.value }
}
export function spaceInfo() {
  if (planSource.value === 'cad' && cadActiveRoomId.value) {
    const room = cadPlanResult.value?.rooms?.find(r => r.id === cadActiveRoomId.value)
    return {
      space_id: cadActiveRoomId.value, space_name: room?.label_zh || '空間',
      space_dims: room ? { w: room.w, d: room.h } : undefined,
      cad_plan: cadPlanPayload(),
    }
  }
  const hasPlan = ['generate', 'upload'].includes(planSource.value)
  return {
    space_id: 'main',
    space_name: spacePhotoPath.value ? '主要空間' : (ROOM_TYPE_LABEL[roomTypeForPlan.value] || '主要空間'),
    space_dims: hasPlan ? { w: roomW.value, d: roomD.value } : undefined,
  }
}
export const cadBatch = ref({})                // 批次生成進行中：{ [roomId]: { status: 'queued'|'running'|'failed', error } }，不存草稿
export const cadBatchRunning = ref(false)
export const cadOverview = ref(false)          // 整層總覽（結果頁的「總覽」分頁）；不存草稿，切到任一房間就關掉
export const cadQuoting = ref({})              // 總覽裡正在估價的房間：{ [roomId]: true }
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
// 風水只問「要不要套用」：開啟後依房型自動挑規則，細調時取消勾選的記在 excluded
export const fengshuiEnabled  = ref(false)
export const fengshuiExcluded = ref([])
// 目前空間實際套用的規則清單（由上面兩個推出來）。可寫入：結果頁的勾選、專案還原會直接
// 設定清單，這裡換算回開關＋排除項，兩種 UI 才不會各存一份互相打架
export const fengshuiRules = computed({
  get() {
    if (!fengshuiEnabled.value) return []
    return relevantRuleValues().filter(v => !fengshuiExcluded.value.includes(v))
  },
  set(list) {
    const rules = list || []
    fengshuiEnabled.value = rules.length > 0
    if (rules.length) fengshuiExcluded.value = relevantRuleValues().filter(v => !rules.includes(v))
  },
})

// 照片／不排家具路徑沒有平面圖步驟，房型在第一頁的 roomType
function relevantRuleValues() {
  const type = planSource.value === 'photo' || planSource.value === 'skip' ? roomType.value : roomTypeForPlan.value
  const hit = FENGSHUI_OPTIONS.filter(o => o.rooms.includes(type))
  return (hit.length ? hit : FENGSHUI_OPTIONS).map(o => o.value)
}
export const outputAspect   = ref('auto')

// ── 空間照片（上傳照片入口）──
export const spacePhoto     = useImageField()
export const spacePhotoPath = ref('')

// ── 風水＋動線健檢 ──
export const fengshuiReport        = ref(null)    // /api/fengshui/audit 的回應（平面圖步驟即時更新）
export const fengshuiReportLoading = ref(false)
export const fengshuiLastFix       = ref(null)    // { moved, previous }：一鍵調整後可以復原
export const photoAudit            = ref(null)    // /api/fengshui/photo-audit 的回應 { plan, report }
export const photoAuditLoading     = ref(false)
export const photoAuditError       = ref('')
// 照片入口：/api/photo-layout 偵測到的原始佈局（還原用）與照片框
export const photoDetection        = ref(null)
export const photoLayoutLoading    = ref(false)
export const photoLayoutError      = ref('')

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
export const candidatesError     = ref('')   // 搜尋失敗的訊息；空字串 = 沒有錯誤
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
// 微調復原堆疊：[{ from: {path,url}, to: 微調後的 path }]。只有 `to` 等於目前圖片時才算可復原，
// 換房間／重新生成後舊的項目自然失效，不用到處清。
export const refineHistory      = ref([])
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

/* ══ 草稿保存（sessionStorage）══════════════════════════════
   重新整理頁面時模組狀態會歸零。這裡只存「路徑 + 表單欄位」——圖片、平面圖、生成結果
   都是大物件或伺服器端產物，還原後反而可能跟畫面對不上，所以不存。
   ponytail: 還原只回到第一步並保留已填欄位；要連步驟一起還原，要先能從伺服器重建結果。 */
const DRAFT_KEY = 'db.flow'
const DRAFT_FIELDS = {
  planSource, roomType, spaceSizePing, customRoomW, customRoomD, furnitureItems, furnitureQty,
  extraPrompt, fengshuiEnabled, fengshuiExcluded, outputAspect, selectedStyle, noStyleReference, styleMethod,
  cadCounts, cadTotalPing, cadRoomW, cadRoomD, cadExtraRooms,   // 整層房型表單（幾房幾廳＋坪數＋長寬），重整後不用重填
}

export function saveDraft() {
  try {
    const d = {}
    for (const k in DRAFT_FIELDS) d[k] = DRAFT_FIELDS[k].value
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(d))
  } catch { /* 無痕模式或儲存空間滿了：沒有草稿而已，不影響流程 */ }
}

export function hasDraft() {
  try { return !!sessionStorage.getItem(DRAFT_KEY) } catch { return false }
}

try {
  const d = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null')
  if (d) for (const k in DRAFT_FIELDS) if (k in d) DRAFT_FIELDS[k].value = d[k]
} catch { /* 壞掉的草稿直接忽略 */ }

watch(Object.values(DRAFT_FIELDS), saveDraft, { deep: true })

/* ── 整層（cad）進度：另存一份 ──
   逐間設計要花很久，重整就全沒了太傷。跟上面的草稿分開存：房間分區圖與每間房的快照
   體積大，不要每打一個字就跟著重寫一次。
   只還原「渲染完成」的房間，並回到「選擇房間」步驟——沒渲染完的那間，畫面上的編輯沒存下來，
   當作還沒開始；其餘步驟的暫存狀態（編輯器、遮罩…）同樣不還原。
   ponytail: 靠 sessionStorage，容量滿了就不留進度（下方 catch），升級路徑是存到後端。 */
const CAD_KEY = 'db.cad'
function saveCadProgress() {
  try {
    if (!cadPlanResult.value) { sessionStorage.removeItem(CAD_KEY); return }
    sessionStorage.setItem(CAD_KEY, JSON.stringify({
      plan: cadPlanResult.value, status: cadRoomStatus.value, snapshots: cadRoomSnapshots.value,
    }))
  } catch {
    try { sessionStorage.removeItem(CAD_KEY) } catch { /* 沒有儲存空間就算了 */ }
  }
}

try {
  const d = JSON.parse(sessionStorage.getItem(CAD_KEY) || 'null')
  if (d?.plan && planSource.value === 'cad') {
    cadPlanResult.value = d.plan
    cadRoomStatus.value = Object.fromEntries(Object.entries(d.status || {}).filter(([, v]) => v === 'done'))
    cadRoomSnapshots.value = Object.fromEntries(
      Object.entries(d.snapshots || {}).filter(([id]) => cadRoomStatus.value[id]),
    )
    stepIndex.value = Math.max(0, steps.value.findIndex(s => s.key === 'roomProgram'))
  }
} catch { /* 壞掉的進度直接忽略 */ }

watch([cadPlanResult, cadRoomStatus, cadRoomSnapshots], saveCadProgress, { deep: true })
