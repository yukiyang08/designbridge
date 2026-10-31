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

// 家具是從渲染圖本身切的，有圖就能移；照片流程另有自己的搬家具工作台
export const canMoveFurniture = computed(() => {
  const r = result.value
  return !!r?.generated_image_path && !String(r.scene_graph?.projection_mode || '').startsWith('photo')
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

// 這張圖上自動切出的每件可移動家具（每張圖第一次約 40 秒，之後後端讀快取）
// plan 不給就是結果頁目前這張；照片工作台傳 { generated_image_path } 指定它的版本
export async function fetchFurnitureInstances(plan = null) {
  const res = await jsonFetch('/api/move-furniture/instances', { plan: plan || planOf(result.value) })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
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

// 指定圖片（照片工作台的版本）上移家具：只回傳新圖，由呼叫端收成新版本，不動結果頁的 result
export async function applyFurnitureMoveOn(plan, moves) {
  applyingMove.value = true
  try {
    const res = await jsonFetch('/api/move-furniture', { plan, moves })
    if (!res.ok) throw new Error(await errorText(res))
    return await res.json()
  } finally {
    applyingMove.value = false
  }
}

// moves = [{ index, x, y }]：每件家具的碰地點拖到的位置（0–1），可一次好幾件
export async function applyFurnitureMove(moves) {
  const requestId = ++requestState.current
  const before = result.value
  applyingMove.value = true
  try {
    const res = await jsonFetch('/api/move-furniture', { plan: planOf(before), moves })
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
