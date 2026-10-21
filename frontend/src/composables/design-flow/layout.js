import { mediaUrl, jsonFetch } from '@/config/api'
import {
  requestState, timers,
  error, loading, loadingMsg, result,
  furnitureItems, furnitureQty, extraPrompt, fengshuiLastFix,
  roomType, spaceSizePing, customRoomW, customRoomD,
  floorPlanUrl, floorPlanPath, sceneGraph, layoutRenderConfig, editPlacements,
  roomW, roomD, roomTypeForPlan,
  floorPlanUpload, uploadedPlanUrl, uploadedPlanPath, detectedRooms, planParseIssue,
  cadDefaultPlacements,
} from './state'
import { nextStep, goToStepKey } from './navigation'
import { scheduleSearch } from './style'
import { uploadFile } from './common'
import { FURNITURE_BY_ROOM } from '@/config/furniture'
import { enterUploadedWholeFloor } from './cad'
import { fengshuiRulesFor } from './fengshui'

/* ══ Step: 空間設定 → 產生 2D 平面圖 ══════════════════════ */

export async function submitLayout() {
  // 這條路徑的第一頁已經不放描述欄位了（描述移到選風格那一步），
  // 所以訊息只提家具，不要叫使用者去找一個畫面上沒有的欄位。
  if (!furnitureItems.value.length && !extraPrompt.value.trim()) {
    error.value = '請至少選擇一件要擺放的家具'
    return
  }
  const requestId = ++requestState.current
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '生成 2D 平面圖中', sub: 'AI 計算家具配置，通常約 10 秒' }
  result.value = null
  try {
    const res = await jsonFetch('/api/generate-layout', {
      room_type:       roomType.value,
      space_size_ping: spaceSizePing.value,
      room_w:          customRoomW.value || undefined,
      room_d:          customRoomD.value || undefined,
      furniture_list:  furnitureItems.value.flatMap(
        t => Array(Math.max(1, furnitureQty.value[t] || 1)).fill(t),
      ),
      text_prompt:    extraPrompt.value,
      fengshui_rules: fengshuiRulesFor(roomType.value),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId !== requestState.current) return
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
    fengshuiLastFix.value = null
    nextStep()
    scheduleSearch()
  } catch (e) {
    if (requestId === requestState.current) error.value = `生成平面圖失敗：${e.message}`
  } finally {
    if (requestId === requestState.current) loading.value = false
  }
}

/* ══ Step: 上傳 2D 平面配置圖 ═══════════════════════════════
   整戶圖（多房間）會先經過「選擇房間」再解析；單一房間圖直接跳過那一步，
   行為等同直接解析整張圖——沿用舊 HomeView.vue 驗證過的三段式寫法。 */

export async function useUploadedPlan() {
  if (!floorPlanUpload.file) {
    error.value = '請先上傳平面配置圖'
    return
  }
  const requestId = ++requestState.current
  error.value = ''
  planParseIssue.value = null
  loading.value = true
  loadingMsg.value = { title: '上傳平面圖中', sub: '處理你的平面配置圖' }
  result.value = null
  try {
    const path = await uploadFile(floorPlanUpload.file)
    if (requestId !== requestState.current) return
    uploadedPlanUrl.value = mediaUrl(path)
    uploadedPlanPath.value = path
    await detectRoomsAndProceed(path, requestId)
  } catch (e) {
    if (requestId === requestState.current) error.value = `解析平面圖失敗：${e.message}`
    if (requestId === requestState.current) loading.value = false
  }
}

// 先看看這張圖是不是含多個房間（整戶圖）——是的話讓使用者先選一間，
// 免得所有房間的家具被混進同一個矩形房間框裡。
// 一間都沒辨識出來時停在這一步讓使用者決定（重試／當單一房間），不默默跳過。
async function detectRoomsAndProceed(path, requestId) {
  loading.value = true
  loadingMsg.value = { title: '辨識房間中', sub: 'AI 判斷這張圖有幾個房間' }
  let rooms = [], plan = null
  let reason = 'empty'
  try {
    const roomsRes = await jsonFetch('/api/detect-rooms', { image_path: path })
    if (!roomsRes.ok) throw new Error(`${roomsRes.status}`)
    ;({ rooms = [], plan = null } = await roomsRes.json())
  } catch {
    reason = 'failed'
  }
  if (requestId !== requestState.current) return

  // 整戶圖切出了整層資料：接進整層流程（整層進度、總覽、批次套用風格）
  if (plan?.rooms?.length > 1) {
    enterUploadedWholeFloor(plan)
    return
  }

  if (!rooms.length) {
    planParseIssue.value = { kind: 'rooms', reason, path }
    loading.value = false
    return
  }
  if (rooms.length > 1) {
    detectedRooms.value = rooms
    loading.value = false
    nextStep() // → 'roomPick'
    return
  }
  await parseFloorPlanAndProceed(path, requestId, rooms[0].room_type)
}

/* ── 解析沒結果時的出口（PlanParseIssue.vue 的按鈕）── */

export async function retryPlanParse() {
  const issue = planParseIssue.value
  if (!issue) return
  const requestId = ++requestState.current
  error.value = ''
  planParseIssue.value = null
  if (issue.kind === 'rooms') await detectRoomsAndProceed(issue.path, requestId)
  else await parseFloorPlanAndProceed(issue.path, requestId, issue.roomType)
}

// 辨識不出房間：整張圖當成一間房去解析家具
export async function parseAsSingleRoom() {
  const issue = planParseIssue.value
  if (!issue) return
  const requestId = ++requestState.current
  error.value = ''
  planParseIssue.value = null
  await parseFloorPlanAndProceed(issue.path, requestId)
}

// 解析不到家具：不排家具，整張平面圖當結構參考生成（原本默默走的後備路徑）
export function continueWithoutFurniture() {
  const issue = planParseIssue.value
  if (!issue) return
  planParseIssue.value = null
  floorPlanPath.value = issue.path
  floorPlanUrl.value = mediaUrl(issue.path)
  sceneGraph.value = null
  editPlacements.value = []
  roomTypeForPlan.value = issue.roomType || roomType.value
  fengshuiLastFix.value = null
  goToStepKey('plan')
}

// ── 使用者從「選擇房間」步驟選定房間後裁切 + 解析 ──
export async function handleRoomSelected(room) {
  const requestId = ++requestState.current
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '裁切房間中', sub: '準備該房間的平面圖' }
  try {
    const res = await jsonFetch('/api/crop-floor-plan', {
      image_path: uploadedPlanPath.value,
      x: room.x, y: room.y, w: room.w, h: room.h,
      polygon: room.polygon || undefined,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const { path: croppedPath } = await res.json()
    if (requestId !== requestState.current) return
    uploadedPlanUrl.value = mediaUrl(croppedPath)

    if (room.room_type === 'other') {
      openEmptyRoom(croppedPath, room)
      return
    }
    await parseFloorPlanAndProceed(croppedPath, requestId, room.room_type)
  } catch (e) {
    if (requestId === requestState.current) error.value = `裁切房間失敗：${e.message}`
    if (requestId === requestState.current) loading.value = false
  }
}

// 佈局引擎不支援的房型（浴室、陽台、未命名空間）：不跑家具辨識，直接進空白的家具配置，
// 讓使用者自己擺。房間尺寸和 /api/parse-floor-plan 用同一套坪數換算。
function openEmptyRoom(croppedPath, room) {
  let w = customRoomW.value, d = customRoomD.value
  if (!(w && d)) {
    const m2 = spaceSizePing.value * 3.306
    w = Math.round(Math.sqrt(m2 * 5 / 4) * 10) / 10
    d = Math.round(Math.sqrt(m2 * 4 / 5) * 10) / 10
  }
  floorPlanPath.value = croppedPath
  floorPlanUrl.value = mediaUrl(croppedPath)
  sceneGraph.value = null
  layoutRenderConfig.value = null
  editPlacements.value = []
  roomW.value = w
  roomD.value = d
  // 浴室／陽台有對應的家具清單；其他未知空間用中性的 room，家具面板會退回預設清單
  roomTypeForPlan.value = FURNITURE_BY_ROOM[room.space_type] ? room.space_type : 'room'
  loading.value = false
  goToStepKey('plan')
  if (extraPrompt.value.trim()) scheduleSearch()
}

// 呼叫 /api/parse-floor-plan → 塞進可編輯的 scene_graph → 進「繪製平面圖」步驟。
// 用 goToStepKey（絕對定位）而不是 nextStep()，因為這個函式在「有無先經過選房間」
// 兩種路徑下都會被呼叫，呼叫當下的 stepIndex 不一樣。
export async function parseFloorPlanAndProceed(path, requestId, roomTypeOverride) {
  loading.value = true
  loadingMsg.value = { title: '解析平面圖中', sub: 'AI 辨識平面圖上的家具配置' }
  try {
    const res = await jsonFetch('/api/parse-floor-plan', {
      image_path: path,
      room_type: roomTypeOverride || roomType.value,
      space_size_ping: spaceSizePing.value,
      room_w: customRoomW.value || undefined,
      room_d: customRoomD.value || undefined,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId !== requestState.current) return

    const placements = (data.furniture_placements || []).map((p, i) => ({
      id: p.id || `item_${i}`, type: p.type, x: p.x, y: p.y, w: p.w, h: p.h, rotation: p.rotation || 0,
    }))
    const resolvedType = data.room_type || roomTypeOverride || roomType.value
    // 客廳沒辨識到家具時給預設擺法；連預設都沒有才停下來讓使用者決定
    const preset = placements.length ? [] : cadDefaultPlacements(resolvedType, data.room_w || 5.0, data.room_d || 4.0)
    if (!placements.length && !preset.length) {
      planParseIssue.value = { kind: 'furniture', reason: 'empty', path, roomType: roomTypeOverride }
      return
    }
    roomW.value = data.room_w || 5.0
    roomD.value = data.room_d || 4.0
    roomTypeForPlan.value = resolvedType
    fengshuiLastFix.value = null
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
      editPlacements.value = preset
      await updateFloorPlan()   // 依預設家具重畫 2D 平面圖
    }
    goToStepKey('plan')
    if (extraPrompt.value.trim()) scheduleSearch()
  } catch {
    if (requestId === requestState.current) {
      planParseIssue.value = { kind: 'furniture', reason: 'failed', path, roomType: roomTypeOverride }
    }
  } finally {
    if (requestId === requestState.current) loading.value = false
  }
}

/* ══ 佈局編輯 ══════════════════════════════════════════════ */

export function onEditorChange(next) {
  editPlacements.value = next
  clearTimeout(timers.floorPlanUpdate)
  timers.floorPlanUpdate = setTimeout(() => {
    timers.floorPlanUpdate = null
    updateFloorPlan()
  }, 500)
}

export async function updateFloorPlan() {
  if (!editPlacements.value.length) return
  try {
    const res = await jsonFetch('/api/render-floor-plan', {
      furniture_placements: editPlacements.value,
      room_w: roomW.value,
      room_d: roomD.value,
      room_type: roomTypeForPlan.value,
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
