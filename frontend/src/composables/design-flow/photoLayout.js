import { jsonFetch } from '@/config/api'
import {
  spacePhotoPath, photoDetection, photoLayoutLoading, photoLayoutError,
  sceneGraph, editPlacements, roomW, roomD, roomTypeForPlan, roomType,
  extraPrompt, floorPlanPath, floorPlanUrl,
} from './state'
import { fengshuiRulesFor } from './fengshui'
import { settlePlacements } from '@/utils/roomGeometry'

/* ══ 照片入口：偵測家具 → 編輯／自動重排 ════════════════════
   sceneGraph 帶 source:'photo'，後端據此把改過的佈局疊回照片深度（見 projected_depth.reproject_scene_graph）。 */

const toEditable = (list) => (list || []).map((p, i) => ({
  id: p.id || `item_${i}`, type: p.type, x: p.x, y: p.y, w: p.w, h: p.h, rotation: p.rotation || 0,
}))

// 編輯器掛載時會把重疊或出界的家具推開；先在這裡做同一件事，偵測基準才不會一打開就被標成「已移動」
const clamp01 = (p) => {
  const w = Math.min(p.w, 1), h = Math.min(p.h, 1)
  return { ...p, w, h, x: Math.max(0, Math.min(1 - w, p.x)), y: Math.max(0, Math.min(1 - h, p.y)) }
}
const settled = (list) => settlePlacements(toEditable(list).map(clamp01), [])

async function errorDetail(res) {
  return (await res.json().catch(() => ({}))).detail || `${res.status}`
}

export async function detectPhotoLayout() {
  if (!spacePhotoPath.value) return false
  photoLayoutLoading.value = true
  photoLayoutError.value = ''
  try {
    const res = await jsonFetch('/api/photo-layout', { image_path: spacePhotoPath.value })
    if (!res.ok) throw new Error(await errorDetail(res))
    const data = await res.json()
    const sg = data.scene_graph
    const baseline = settled(sg.furniture_placements)
    photoDetection.value = { ...sg, baseline }
    sceneGraph.value = sg
    editPlacements.value = baseline
    roomW.value = sg.room_w
    roomD.value = sg.room_d
    roomTypeForPlan.value = sg.room_type
    roomType.value = sg.room_type
    // 照片流程不畫平面圖，清掉其他路徑殘留的
    floorPlanPath.value = ''
    floorPlanUrl.value = ''
    return true
  } catch (e) {
    photoLayoutError.value = `家具偵測失敗：${e.message}`
    return false
  } finally {
    photoLayoutLoading.value = false
  }
}

export function resetPhotoLayout() {
  if (photoDetection.value) editPlacements.value = photoDetection.value.baseline
}

// 同一組家具交給 layout agent 重排，門窗用照片偵測到的
export async function autoRelayoutPhoto() {
  const det = photoDetection.value
  if (!det || photoLayoutLoading.value) return
  photoLayoutLoading.value = true
  photoLayoutError.value = ''
  try {
    const res = await jsonFetch('/api/generate-layout', {
      room_type: roomTypeForPlan.value,
      room_w: roomW.value,
      room_d: roomD.value,
      furniture_list: editPlacements.value.map(p => p.type),
      text_prompt: extraPrompt.value,
      fengshui_rules: fengshuiRulesFor(roomTypeForPlan.value),
      doors: det.doors,
      windows: det.windows,
    })
    if (!res.ok) throw new Error(await errorDetail(res))
    const data = await res.json()
    const next = toEditable(data.scene_graph?.furniture_placements)
    if (!next.length) throw new Error('沒有排出任何家具')
    // layout agent 會重新編 id；同類型依序對回原本的家具，照片上的框才知道是誰被移動
    const pool = editPlacements.value.map(p => ({ id: p.id, type: p.type }))
    editPlacements.value = next.map(p => {
      const i = pool.findIndex(o => o.type === p.type)
      return i < 0 ? p : { ...p, id: pool.splice(i, 1)[0].id }
    })
  } catch (e) {
    photoLayoutError.value = `自動重排失敗：${e.message}`
  } finally {
    photoLayoutLoading.value = false
  }
}
