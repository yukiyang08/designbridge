import { mediaUrl, jsonFetch } from '@/config/api'
import {
  requestState, timers,
  error, loading, loadingMsg, result,
  furnitureItems, furnitureQty, extraPrompt, fengshuiRules,
  roomType, spaceSizePing, customRoomW, customRoomD,
  floorPlanUrl, floorPlanPath, sceneGraph, layoutRenderConfig, editPlacements,
  roomW, roomD, roomTypeForPlan,
  floorPlanUpload, uploadedPlanUrl, uploadedPlanPath, detectedRooms,
} from './state'
import { nextStep, goToStepKey } from './navigation'
import { scheduleSearch } from './style'
import { uploadFile } from './common'

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
      fengshui_rules: fengshuiRules.value,
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
  loading.value = true
  loadingMsg.value = { title: '上傳平面圖中', sub: '處理你的平面配置圖' }
  result.value = null
  try {
    const path = await uploadFile(floorPlanUpload.file)
    if (requestId !== requestState.current) return
    uploadedPlanUrl.value = mediaUrl(path)
    uploadedPlanPath.value = path

    // 先看看這張圖是不是含多個房間（整戶圖）——是的話讓使用者先選一間，
    // 免得所有房間的家具被混進同一個矩形房間框裡。
    let rooms = []
    try {
      const roomsRes = await jsonFetch('/api/detect-rooms', { image_path: path })
      if (roomsRes.ok) rooms = (await roomsRes.json()).rooms || []
    } catch {
      rooms = [] // 偵測失敗就當單一房間處理，不擋住原本的流程
    }
    if (requestId !== requestState.current) return

    if (rooms.length > 1) {
      detectedRooms.value = rooms
      loading.value = false
      nextStep() // → 'roomPick'
      return
    }

    await parseFloorPlanAndProceed(path, requestId, rooms[0]?.room_type)
  } catch (e) {
    if (requestId === requestState.current) error.value = `解析平面圖失敗：${e.message}`
    if (requestId === requestState.current) loading.value = false
  }
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
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const { path: croppedPath } = await res.json()
    if (requestId !== requestState.current) return
    uploadedPlanUrl.value = mediaUrl(croppedPath)

    await parseFloorPlanAndProceed(croppedPath, requestId, room.room_type)
  } catch (e) {
    if (requestId === requestState.current) error.value = `裁切房間失敗：${e.message}`
    if (requestId === requestState.current) loading.value = false
  }
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
    goToStepKey('plan')
    if (extraPrompt.value.trim()) scheduleSearch()
  } catch (e) {
    if (requestId === requestState.current) error.value = `解析平面圖失敗：${e.message}`
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
