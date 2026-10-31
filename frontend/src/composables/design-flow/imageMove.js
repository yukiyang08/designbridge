import { ref } from 'vue'
import { jsonFetch } from '@/config/api'
import { result, lastGeneratedImage, refineHistory, planSource, cadActiveRoomId } from './state'
import { snapshotCurrentCadRoom } from './cad'

/* ══ 在任何一張圖上搬家具（照片入口、直接描述的結果）══════════════
   CAD 的結果圖有相機與家具配置，走 move.js；這裡只靠影像：點選 → 拖曳 → 一次 inpaint。 */

export const applyingImageMove = ref(false)

async function errorText(res) {
  const body = await res.json().catch(() => ({}))
  return body.detail || `HTTP ${res.status}`
}

export async function pickImageFurniture(imagePath, x, y) {
  const res = await jsonFetch('/api/image-move/pick', { image_path: imagePath, x, y })
  if (!res.ok) throw new Error(await errorText(res))
  const data = await res.json()
  return data.mask_path ? data : null
}

// 回傳 { generated_image_path, generated_image_url }；呼叫端決定怎麼收（結果頁換圖、照片工作台加一個版本）
export async function moveImageFurniture(imagePath, picked, to) {
  applyingImageMove.value = true
  try {
    const res = await jsonFetch('/api/image-move', {
      image_path: imagePath, mask_path: picked.mask_path, x: to.x, y: to.y, horizon_y: picked.horizon_y,
    })
    if (!res.ok) throw new Error(await errorText(res))
    return await res.json()
  } finally {
    applyingImageMove.value = false
  }
}

// 結果頁：跟微調共用同一份歷史，「復原」按鈕照樣能退回搬之前
export function adoptMovedResult(data) {
  const before = lastGeneratedImage.value || { path: result.value?.generated_image_path, url: result.value?.generated_image_url }
  result.value = { ...(result.value || {}), ...data, quotation_result: null }   // 圖變了，舊報價作廢
  if (before?.path) refineHistory.value.push({ from: before, to: data.generated_image_path })
  lastGeneratedImage.value = { path: data.generated_image_path, url: data.generated_image_url || null }
  if (planSource.value === 'cad' && cadActiveRoomId.value) snapshotCurrentCadRoom()
}
