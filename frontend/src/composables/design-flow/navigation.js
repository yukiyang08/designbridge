import { cancelCadBatch } from './cadBatch'
import {
  steps, stepIndex, error, planSource,
  floorPlanUrl, floorPlanPath, sceneGraph, editPlacements, layoutViewMode, layoutRenderConfig,
  floorPlanUpload, uploadedPlanUrl, uploadedPlanPath, detectedRooms,
  cadPlanResult, cadActiveRoomId, cadRoomStatus, cadRoomSnapshots,
  spacePhoto, spacePhotoPath, spaceImage, styleRefImage,
  result, loading,
  styleCandidates, styleCandidatePool, candidatesSearched, confirmedStyle, matchedStylePreview,
  lastGeneratedImage, manualMaskPath, refineHistory, textPrompt,
  panoUrl, panoError, panoLoading, quotationError,
  timers, saveDraft,
} from './state'

export function goStep(i) {
  stepIndex.value = Math.max(0, Math.min(steps.value.length - 1, i))
  error.value = ''
}
export function nextStep() { goStep(stepIndex.value + 1) }
export function prevStep() { goStep(stepIndex.value - 1) }

// 用步驟 key（而不是絕對 index）跳頁——同一個 key 在不同入口路徑（generate/upload/cad…）
// 對應到的 index 不一樣，呼叫端不用自己 import steps 再 findIndex。
export function goToStepKey(key) {
  goStep(steps.value.findIndex(s => s.key === key))
}

export function startFlow(source) {
  resetFlow()
  planSource.value = source
  stepIndex.value = 0
  saveDraft()   // 路由守衛靠它判斷「是從入口頁進來的」
}

export function resetFlow() {
  planSource.value = 'generate'
  stepIndex.value = 0
  floorPlanUrl.value = ''
  floorPlanPath.value = ''
  sceneGraph.value = null
  editPlacements.value = []
  clearTimeout(timers.floorPlanUpdate); timers.floorPlanUpdate = null
  clearTimeout(timers.search); timers.search = null
  layoutViewMode.value = '2d'
  layoutRenderConfig.value = null
  floorPlanUpload.remove()
  uploadedPlanUrl.value = ''
  uploadedPlanPath.value = ''
  detectedRooms.value = []
  cadPlanResult.value = null
  cadActiveRoomId.value = null
  cadRoomStatus.value = {}
  cadRoomSnapshots.value = {}
  cancelCadBatch()
  spacePhoto.remove()
  spacePhotoPath.value = ''
  spaceImage.remove()
  styleRefImage.remove()
  result.value = null
  error.value = ''
  loading.value = false
  styleCandidates.value = []
  styleCandidatePool.value = []
  candidatesSearched.value = false
  confirmedStyle.value = null
  matchedStylePreview.value = null
  lastGeneratedImage.value = null
  manualMaskPath.value = ''
  refineHistory.value = []
  textPrompt.value = ''
  panoUrl.value = null
  panoError.value = ''
  panoLoading.value = false
  quotationError.value = ''
}
