import { jsonFetch } from '@/config/api'
import {
  requestState,
  error, loading, loadingMsg, result,
  refineCanvasRef, manualMaskPath, lastGeneratedImage, spacePhotoPath, spaceImage,
  outputAspect, textPrompt, planSource, cadActiveRoomId,
} from './state'
import { uploadFile } from './common'
import { snapshotCurrentCadRoom } from './cad'

/* ══ Step: 微調編輯 ══════════════════════════════════════ */

export async function handleMaskReady(blob) {
  const file = new File([blob], 'mask.png', { type: 'image/png' })
  manualMaskPath.value = await uploadFile(file)
}

export async function submitRefine() {
  if (!textPrompt.value.trim()) { error.value = '請輸入調整需求'; return }
  const requestId = ++requestState.current
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '套用微調中', sub: 'AI 只重繪你塗抹的區域，其餘保持不變' }
  try {
    let mask_image_path
    const maskBlob = await refineCanvasRef.value?.getMaskBlob()
    if (maskBlob) {
      mask_image_path = await uploadFile(new File([maskBlob], 'mask.png', { type: 'image/png' }))
      manualMaskPath.value = mask_image_path
    }

    const initial_image_path = lastGeneratedImage.value?.path
      || spacePhotoPath.value
      || (spaceImage.file ? await uploadFile(spaceImage.file) : undefined)

    const res = await jsonFetch('/api/generate', {
      text_prompt: textPrompt.value,
      initial_image_path,
      no_style_reference: true,
      refine_mode: true,
      output_aspect: outputAspect.value,
      mask_image_path,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId === requestState.current) {
      result.value = { ...(result.value || {}), ...data }
      if (data.generated_image_path) {
        lastGeneratedImage.value = { path: data.generated_image_path, url: data.generated_image_url || null }
      }
      // 微調也是同一間房的最新結果，重新存一次快照，回來看到的才是微調後的版本
      if (planSource.value === 'cad' && cadActiveRoomId.value) snapshotCurrentCadRoom()
    }
  } catch (e) {
    if (requestId === requestState.current) error.value = `微調失敗：${e.message}`
  } finally {
    if (requestId === requestState.current) loading.value = false
  }
}
