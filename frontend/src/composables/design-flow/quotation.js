import { jsonFetch } from '@/config/api'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import {
  lastGeneratedImage, result, quotationLoading, quotationError,
  favoriteLoading, favoriteError,
} from './state'

/* ══ Step: 預算估計 ══════════════════════════════════════ */

export async function fetchQuotation() {
  const imagePath = lastGeneratedImage.value?.path || result.value?.generated_image_path
  if (!imagePath) return
  const { selectedFurniture } = useFurnitureSelection()
  quotationLoading.value = true
  quotationError.value = ''
  try {
    const res = await jsonFetch('/api/quotation', {
      image_path: imagePath,
      structured_requirement: result.value?.structured_requirement || null,
      selected_furniture: selectedFurniture.value,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    result.value = { ...(result.value || {}), quotation_result: data }
  } catch (e) {
    quotationError.value = e.message || '估價失敗，請稍後再試'
  } finally {
    quotationLoading.value = false
  }
}

/* ══ 收藏這個設計 ══════════════════════════════════════ */

export async function toggleFavoriteDesign(next) {
  const taskId = result.value?.task_id
  if (!taskId) return
  const favorited = next ?? !result.value?.favorited
  favoriteLoading.value = true
  favoriteError.value = ''
  try {
    const res = await jsonFetch(`/api/history/${encodeURIComponent(taskId)}/favorite`, { favorited }, 'PATCH')
    if (!res.ok) throw new Error(`${res.status}`)
    result.value = { ...(result.value || {}), favorited }
  } catch (e) {
    favoriteError.value = '收藏失敗，請稍後再試'
  } finally {
    favoriteLoading.value = false
  }
}
