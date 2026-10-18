import { jsonFetch } from '@/config/api'
import {
  requestState, cadDefaultPlacements, CAD_ROOM_TYPE_TO_EDITOR,
  error, loading, loadingMsg, result,
  cadCounts, cadTotalPing, cadRoomW, cadRoomD, cadExtraRooms, cadPlanResult, cadRendering, cadRenderError,
  cadActiveRoomId, cadRoomStatus, cadRoomSnapshots, cadBatch, openingEdits, roomGeometry, cadOverview,
  roomW, roomD, roomTypeForPlan, editPlacements,
  floorPlanPath, floorPlanUrl, sceneGraph, layoutRenderConfig, lastGeneratedImage,
  uploadedPlanUrl, panoUrl, panoError,
} from './state'
import { goToStepKey } from './navigation'
import { cancelCadBatch } from './cadBatch'

/* ══ Step: CAD 房型生成 ═══════════════════════════════════
   輸入幾房幾廳＋總坪數 → /api/generate-room-plan 直接切割出整層樓的房間配置
   （牆／門／窗，結構化資料，不需要再像上傳流程那樣用 Gemini 視覺辨識）。多房間時
   房間選擇器就在 StepRoomProgram 同一頁的表單下方展開，不跳頁；使用者選一間後
   才落地成單房間的 scene_graph 交給既有的 LayoutEditor（goToStepKey('plan')）。 */

// 只取平面圖、不動畫面狀態（不顯示整頁載入、不清進度）：整層房型頁「改了設定就即時更新」用。
// 這裡不會清掉已設計的房間，所以呼叫端要先確認目前沒有任何進度。
export async function fetchRoomPlan() {
  // 長寬兩個都有才送：後端會以 長×寬 為準換算坪數（見 routers/floorplan.py 的 RoomProgramRequest）
  const size = cadRoomW.value > 0 && cadRoomD.value > 0 ? { room_w: cadRoomW.value, room_d: cadRoomD.value } : {}
  const res = await jsonFetch('/api/generate-room-plan', { ...cadCounts.value, total_ping: cadTotalPing.value, ...size, extra_rooms: cadExtraRooms.value })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || `${res.status}`)
  return data
}

export async function submitRoomProgram() {
  const requestId = ++requestState.current
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '生成房型配置中', sub: '依房型配置切割空間、繪製牆體與門窗' }
  result.value = null
  try {
    // 長寬兩個都有才送：後端會以 長×寬 為準換算坪數（見 routers/floorplan.py 的 RoomProgramRequest）
    const size = cadRoomW.value > 0 && cadRoomD.value > 0 ? { room_w: cadRoomW.value, room_d: cadRoomD.value } : {}
    const res = await jsonFetch('/api/generate-room-plan', { ...cadCounts.value, total_ping: cadTotalPing.value, ...size, extra_rooms: cadExtraRooms.value })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || `${res.status}`)
    if (requestId !== requestState.current) return
    // 新的一層：舊的房間 id（bedroom_0…）會跟新分區撞名，不清掉就會還原到舊平面圖的快照
    cadActiveRoomId.value = null
    cadRoomStatus.value = {}
    cadRoomSnapshots.value = {}
    cadOverview.value = false
    cadRendering.value = {}
    cadRenderError.value = {}
    for (const k of Object.keys(cadRenderTokens)) cadRenderTokens[k]++   // 舊平面圖還在跑的渲染作廢（房間 id 會撞名）
    openingEdits.value = {}
    cancelCadBatch()
    cadPlanResult.value = data
    if ((data.rooms || []).length > 1) {
      // 多房間：房間選擇器就在這一頁的表單下方展開，不跳頁，使用者直接點房間繼續。
      loading.value = false
      return
    }
    if (data.rooms?.[0]) await handleCadRoomSelected(data.rooms[0], requestId)
    else { error.value = '沒有可用的房間，請調整房型配置'; loading.value = false }
  } catch (e) {
    if (requestId === requestState.current) { error.value = `生成房型配置失敗：${e.message}`; loading.value = false }
  }
}

export function setOpeningEdit(id, patch) {
  const key = `${cadActiveRoomId.value}:${id}`
  openingEdits.value = { ...openingEdits.value, [key]: { ...openingEdits.value[key], ...patch } }
}

// 把目前這間房相關的狀態存一份快照，供之後從縮圖切回來還原用。
export function snapshotCurrentCadRoom() {
  const id = cadActiveRoomId.value
  if (!id) return
  cadRoomSnapshots.value = {
    ...cadRoomSnapshots.value,
    [id]: {
      roomW: roomW.value, roomD: roomD.value, roomTypeForPlan: roomTypeForPlan.value,
      editPlacements: editPlacements.value, floorPlanPath: floorPlanPath.value, floorPlanUrl: floorPlanUrl.value,
      sceneGraph: sceneGraph.value, layoutRenderConfig: layoutRenderConfig.value,
      result: result.value, lastGeneratedImage: lastGeneratedImage.value,
      panoUrl: panoUrl.value,
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
  panoUrl.value = snap.panoUrl || null   // 環景是每間房各自的，不能跟著全域殘留到別間
  panoError.value = ''
  return true
}

// 使用者從「選擇房間」／右上角縮圖選定一間房後，把它的絕對座標矩形換算成單房間的
// roomW/roomD。回頭選過的房間（cadRoomSnapshots 裡已經有）直接還原上次的進度；
// 第一次選的房間才用 cadDefaultPlacements 的預設家具跟 render-floor-plan 要一張底圖。
// 已完成的房間：點了直接看它的生成結果（「生成設計」步驟）；還沒完成的才回「繪製平面圖」繼續編輯。
// 想改已完成房間的家具，從結果頁用步驟列回到「繪製平面圖」。
// 正在渲染的房間也進結果頁（那裡會顯示「生成中」）。
const stepForRoom = (id) => ((cadRoomStatus.value[id] === 'done' && result.value) || cadRendering.value[id] ? 'result' : 'plan')

export async function handleCadRoomSelected(room, requestId = ++requestState.current) {
  cadOverview.value = false   // 選了任何一間房就離開整層總覽
  const activeId = cadActiveRoomId.value
  if (activeId === room.id) {
    // 選的就是正在做的那間：直接回去繼續，不能重新載入（會把還沒渲染的編輯蓋掉）
    goToStepKey(stepForRoom(room.id))
    return
  }
  if (['queued', 'running'].includes(cadBatch.value[room.id]?.status)) {
    // 批次還在生成這間：現在進去編輯，完成時會把使用者的編輯蓋掉（失敗的不擋，可以進去改）
    error.value = `「${cadRoomLabel(room.id)}」正在批次生成中，完成後再進入編輯`
    return
  }
  // 隨時都可以切去別間：目前這間的編輯先存進它自己的快照（回來時還原）；如果它正在渲染，
  // 結果會在背景寫進同一份快照（見 render.js 的 submit3D）。
  if (activeId) snapshotCurrentCadRoom()
  cadActiveRoomId.value = room.id
  if (!cadRoomStatus.value[room.id]) {
    cadRoomStatus.value = { ...cadRoomStatus.value, [room.id]: 'active' }
  }
  uploadedPlanUrl.value = cadPlanResult.value?.svg_url || ''

  if (restoreCadRoomSnapshot(room.id)) {
    goToStepKey(stepForRoom(room.id))   // 換步驟會順手清掉 error，所以顯示錯誤要放在它後面
    // 離開期間渲染失敗了：回來時才告訴使用者
    const failed = cadRenderError.value[room.id]
    if (failed) {
      error.value = failed
      const { [room.id]: _f, ...rest } = cadRenderError.value
      cadRenderError.value = rest
    }
    return
  }

  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '準備房間底圖中', sub: '生成預設家具配置與平面圖' }
  try {
    result.value = null              // 全新的房間不能沿用上一間的渲染結果
    lastGeneratedImage.value = null
    panoUrl.value = null
    panoError.value = ''
    roomW.value = room.w
    roomD.value = room.h
    roomTypeForPlan.value = CAD_ROOM_TYPE_TO_EDITOR[room.room_type] || 'living_room'
    sceneGraph.value = null
    editPlacements.value = cadDefaultPlacements(roomTypeForPlan.value, roomW.value, roomD.value, roomGeometry.value)

    const res = await jsonFetch('/api/render-floor-plan', {
      furniture_placements: editPlacements.value,
      room_w: roomW.value,
      room_d: roomD.value,
      room_type: roomTypeForPlan.value,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId !== requestState.current) return
    floorPlanPath.value = data.floor_plan_path || ''
    floorPlanUrl.value = data.floor_plan_url || ''
    goToStepKey('plan')
  } catch (e) {
    if (requestId === requestState.current) error.value = `準備房間底圖失敗：${e.message}`
  } finally {
    if (requestId === requestState.current) loading.value = false
  }
}

// 縮圖上點別間房——只有目前這間已經渲染完成（cadRoomStatus === 'done'）才會被呼叫
// （縮圖元件自己也擋，這裡再擋一次避免中途跳房弄亂進度）。
export function jumpToCadRoom(room) {
  handleCadRoomSelected(room)   // 規則與存快照都在裡面
}

// 渲染一直失敗、或單純不想做這間：丟掉它的進度，回「選擇房間」改選別間。
// 已完成的房間不能放棄（那是成果）。
export function abandonCadRoom() {
  const id = cadActiveRoomId.value
  if (!id || cadRoomStatus.value[id] === 'done') return
  const { [id]: _s, ...status } = cadRoomStatus.value
  const { [id]: _n, ...snaps } = cadRoomSnapshots.value
  cadRoomStatus.value = status
  cadRoomSnapshots.value = snaps
  cadActiveRoomId.value = null
  error.value = ''
  goToStepKey('roomProgram')
}

export function cadRoomLabel(id) {
  return cadPlanResult.value?.rooms?.find(r => r.id === id)?.label_zh || '這間房'
}
