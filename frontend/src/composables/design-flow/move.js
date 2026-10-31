import { computed, ref } from 'vue'
import { jsonFetch, mediaUrl } from '@/config/api'
import {
  requestState,
  result, lastGeneratedImage, editPlacements, sceneGraph, floorPlanPath, floorPlanUrl,
  planSource, cadActiveRoomId, styleSwapCache,
} from './state'
import { snapshotCurrentCadRoom } from './cad'
import { ORIGINAL_STYLE_KEY } from './render'

/* ══ 在渲染圖上拖曳家具 ════════════════════════════════════
   點家具 → /api/move-furniture/pick 回傳圖層，前端即時拖曳預覽；
   按「套用」→ /api/move-furniture 用剪貼合成圖 + 新深度圖重修一次，不從零重生。 */

export const applyingMove = ref(false)
const moveHistory = ref([])   // 每次套用前的整份 result，復原用

// 只有合成相機的投影能換算回地板座標（照片流程的投影是照片本身的幾何）
export const canMoveFurniture = computed(() => {
  const sg = result.value?.scene_graph
  return !!sg?.furniture_placements?.length && (!sg.projection_mode || sg.projection_mode === 'synthetic')
})
export const canUndoMove = computed(() => {
  const last = moveHistory.value.at(-1)
  return !!last && last.to === result.value?.generated_image_path
})

// 報價跟換款紀錄跟移家具無關，不用整包送回去
function planOf(r) {
  const { quotation_result: _q, ...plan } = r || {}
  return plan
}

async function errorText(res) {
  const body = await res.json().catch(() => ({}))
  return body.detail || `HTTP ${res.status}`
}

export async function pickFurniture(x, y) {
  const res = await jsonFetch('/api/move-furniture/pick', { plan: planOf(result.value), x, y })
  if (!res.ok) throw new Error(await errorText(res))
  const data = await res.json()
  return data.id ? data : null
}

function adopt(data) {
  result.value = data
  if (data.generated_image_path) {
    lastGeneratedImage.value = { path: data.generated_image_path, url: data.generated_image_url || null }
  }
  // 2D 佈局跟著新位置走；編輯器自己的欄位（鎖定等）保留
  const next = new Map((data.scene_graph?.furniture_placements || []).map(p => [String(p.id), p]))
  if (editPlacements.value.length) {
    editPlacements.value = editPlacements.value.map(p => {
      const q = next.get(String(p.id))
      return q ? { ...p, x: q.x, y: q.y, w: q.w, h: q.h, ...(q.front ? { front: q.front } : {}) } : p
    })
  }
  sceneGraph.value = data.scene_graph || sceneGraph.value
  if (data.floor_plan_path) {
    floorPlanPath.value = data.floor_plan_path
    floorPlanUrl.value = data.floor_plan_url || mediaUrl(data.floor_plan_path)
  }
  if (planSource.value === 'cad' && cadActiveRoomId.value) snapshotCurrentCadRoom()
}

// drag = { id, x, y }：家具地板錨點拖到的位置（0–1）
export async function applyFurnitureMove(drag) {
  const requestId = ++requestState.current
  const before = result.value
  applyingMove.value = true
  try {
    const res = await jsonFetch('/api/move-furniture', { plan: planOf(before), drag })
    if (!res.ok) throw new Error(await errorText(res))
    const data = await res.json()
    if (requestId !== requestState.current) return
    moveHistory.value.push({ from: before, to: data.generated_image_path })
    adopt({ ...data, quotation_result: null })   // 圖變了，舊報價作廢
    // 其他風格的快取還是舊佈局，留著會切回家具沒移過的版本；原圖留著當紀錄
    const styleId = data.style_params?.style_profile_id
    styleSwapCache.value = {
      [ORIGINAL_STYLE_KEY]: styleSwapCache.value[ORIGINAL_STYLE_KEY],
      ...(styleId ? { [styleId]: result.value } : {}),
    }
  } finally {
    if (requestId === requestState.current) applyingMove.value = false
  }
}

export function undoMove() {
  if (!canUndoMove.value) return
  adopt(moveHistory.value.pop().from)
}
