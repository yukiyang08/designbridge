import { jsonFetch } from '@/config/api'
import {
  ROOM_TYPE_LABEL, requestState, timers,
  error, loading, loadingMsg, result, submitKey,
  spacePhoto, spacePhotoPath,
  styleRefImage, confirmedStyle, noStyleReference, selectedStyle, styleMethod,
  editPlacements, sceneGraph, floorPlanPath,
  extraPrompt, familyNeeds, fengshuiRules, outputAspect, roomTypeForPlan, spaceSizePing,
  planSource, cadActiveRoomId, cadRoomStatus, lastGeneratedImage,
  panoLoading, panoUrl, panoError,
} from './state'
import { nextStep } from './navigation'
import { scheduleSearch } from './style'
import { uploadFile } from './common'
import { updateFloorPlan } from './layout'
import { snapshotCurrentCadRoom } from './cad'

/* ══ Step: 上傳空間照片 ════════════════════════════════════
   照片走 /api/generate 的 initial_image_path：visual_preprocessing 會抽視覺特徵、
   requirement agent 會把照片一起餵給 Gemini，所以不需要新的後端端點。 */

export async function submitPhoto() {
  if (!spacePhoto.file) {
    error.value = '請先上傳空間照片'
    return
  }
  error.value = ''
  loading.value = true
  loadingMsg.value = { title: '上傳空間照片中', sub: '準備分析你的空間' }
  try {
    spacePhotoPath.value = await uploadFile(spacePhoto.file)
    nextStep()
    scheduleSearch()
  } catch (e) {
    error.value = `上傳失敗：${e.message}`
  } finally {
    loading.value = false
  }
}

/* ══ Step: 3D 渲染 ════════════════════════════════════════ */

export async function submit3D() {
  if (timers.floorPlanUpdate) {
    clearTimeout(timers.floorPlanUpdate)
    timers.floorPlanUpdate = null
    await updateFloorPlan()
  }
  const requestId = ++requestState.current
  submitKey.value++
  error.value = ''
  result.value = null
  loading.value = true
  loadingMsg.value = { title: '生成 3D 渲染圖中', sub: 'AI 將平面配置轉為立體室內透視，通常約 30–60 秒' }
  panoUrl.value = null
  panoError.value = ''
  try {
    let style_reference_image_path
    if (!noStyleReference.value) {
      if (styleRefImage.file) style_reference_image_path = await uploadFile(styleRefImage.file)
      else if (confirmedStyle.value?.image_url) style_reference_image_path = confirmedStyle.value.image_url
    }

    const editedSceneGraph = editPlacements.value.length
      ? {
          ...(sceneGraph.value || {}),
          furniture_placements: editPlacements.value,
          floor_plan_path: floorPlanPath.value || sceneGraph.value?.floor_plan_path,
        }
      : undefined

    // 跳過排版時沒有 scene_graph、沒有平面圖、也沒有照片，房型與坪數就沒有任何
    // 欄位可以承載（DesignRequest 沒有 room_type / space_size）。折進 text_prompt，
    // 使用者在第一步選的東西才真的會影響生成結果，而不是選了等於沒選。
    const noSpatialInput = !editedSceneGraph && !floorPlanPath.value && !spacePhotoPath.value
    const spacePreamble = noSpatialInput
      ? `${ROOM_TYPE_LABEL[roomTypeForPlan.value] || ''}，約 ${spaceSizePing.value} 坪。`
      : ''

    const res = await jsonFetch('/api/generate', {
      text_prompt:      (spacePreamble + extraPrompt.value).trim(),
      style_profile_id: !noStyleReference.value && selectedStyle.value !== 'auto'
        ? selectedStyle.value
        : !noStyleReference.value ? confirmedStyle.value?.style_id || undefined : undefined,
      style_reference_image_path,
      no_style_reference: noStyleReference.value,
      refine_mode:        false,
      output_aspect:      outputAspect.value,
      style_method:       styleMethod.value,
      family_needs:       familyNeeds.value,
      fengshui_rules:     fengshuiRules.value,
      // 上傳照片路徑：把照片當作生成的起始影像
      initial_image_path: spacePhotoPath.value || undefined,
      floor_plan_path:    floorPlanPath.value || undefined,
      scene_graph:        editedSceneGraph,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId === requestState.current) {
      result.value = data
      if (data.generated_image_path) {
        lastGeneratedImage.value = { path: data.generated_image_path, url: data.generated_image_url || null }
      }
      // CAD 多房間流程：這間房的 3D 渲染圖生成完成才算「完成」，縮圖到這裡才會解鎖、
      // 可以點去別間房（見 jumpToCadRoom）。
      if (planSource.value === 'cad' && cadActiveRoomId.value) {
        cadRoomStatus.value = { ...cadRoomStatus.value, [cadActiveRoomId.value]: 'done' }
        snapshotCurrentCadRoom()
      }
    }
  } catch (e) {
    if (requestId === requestState.current) error.value = `生成渲染圖失敗：${e.message}`
  } finally {
    if (requestId === requestState.current) loading.value = false
  }
}

/* ══ Step: 360° 環景 ══════════════════════════════════════ */

export async function generatePanorama() {
  const r = result.value
  if (!r?.task_id || !r?.generated_image_path) return
  panoLoading.value = true
  panoError.value = ''
  try {
    const res = await jsonFetch('/api/generate-panorama', {
      task_id: r.task_id,
      image_path: r.generated_image_path,
      depth_path: r.vision_features?.depth || null,
      prompt: r.structured_requirement?.meta?.design_goal || '',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    panoUrl.value = data.room_panorama_url
  } catch (e) {
    panoError.value = e.message
  } finally {
    panoLoading.value = false
  }
}
