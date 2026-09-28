import { jsonFetch } from '@/config/api'
import {
  requestState, cadDefaultPlacements, CAD_ROOM_TYPE_TO_EDITOR,
  error, loading, loadingMsg, result,
  cadCounts, cadTotalPing, cadPlanResult,
  cadActiveRoomId, cadRoomStatus, cadRoomSnapshots,
  roomW, roomD, roomTypeForPlan, editPlacements,
  floorPlanPath, floorPlanUrl, sceneGraph, layoutRenderConfig, lastGeneratedImage,
  uploadedPlanUrl,
} from './state'
import { nextStep, goToStepKey } from './navigation'

/* ══ Step: CAD 房型生成 ═══════════════════════════════════
   輸入幾房幾廳＋總坪數 → /api/generate-room-plan 直接切割出整層樓的房間配置
   （牆／門／窗，結構化資料，不需要再像上傳流程那樣用 Gemini 視覺辨識），一定是
   多房間，所以固定進「選擇房間」步驟，使用者選一間後才落地成單房間的
   scene_graph 交給既有的 LayoutEditor。 */

export async function submitRoomProgram() {
  const requestId = ++requestState.current
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '生成房型配置中', sub: '依房型配置切割空間、繪製牆體與門窗' }
  result.value = null
  try {
    const res = await jsonFetch('/api/generate-room-plan', { ...cadCounts.value, total_ping: cadTotalPing.value })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || `${res.status}`)
    if (requestId !== requestState.current) return
    cadPlanResult.value = data
    if ((data.rooms || []).length > 1) {
      loading.value = false
      nextStep() // → 'roomPick'
      return
    }
    if (data.rooms?.[0]) await handleCadRoomSelected(data.rooms[0], requestId)
    else { error.value = '沒有可用的房間，請調整房型配置'; loading.value = false }
  } catch (e) {
    if (requestId === requestState.current) { error.value = `生成房型配置失敗：${e.message}`; loading.value = false }
  }
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
export async function handleCadRoomSelected(room, requestId = ++requestState.current) {
  cadActiveRoomId.value = room.id
  if (!cadRoomStatus.value[room.id]) {
    cadRoomStatus.value = { ...cadRoomStatus.value, [room.id]: 'active' }
  }
  uploadedPlanUrl.value = cadPlanResult.value?.svg_url || ''

  if (restoreCadRoomSnapshot(room.id)) {
    goToStepKey('plan')
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
  const activeId = cadActiveRoomId.value
  if (activeId && cadRoomStatus.value[activeId] !== 'done') return
  if (room.id === activeId) return
  snapshotCurrentCadRoom()
  handleCadRoomSelected(room)
}
