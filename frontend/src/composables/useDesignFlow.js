/**
 * 整條設計流程的狀態與 API 呼叫，對外的組裝入口。
 *
 * 實際的狀態與邏輯依 domain 拆到 ./design-flow/ 底下：
 *  - state.js      模組層級狀態、常數、衍生值
 *  - navigation.js  步驟導航、重設流程
 *  - common.js      上傳檔案、等後端啟動
 *  - style.js       風格選項／搜尋
 *  - layout.js      2D 平面圖生成／上傳解析／佈局編輯
 *  - cad.js         CAD 房型生成、多房間逐一設計
 *  - render.js      空間照片、3D 渲染、360° 環景
 *  - refine.js      微調編輯
 *  - quotation.js   預算估計、收藏
 *
 * 這裡只做組裝，不放邏輯——拆檔前後 useDesignFlow() 回傳的形狀完全一致，
 * 呼叫端（各 Step 元件）不用改。
 */

export { STEP_FLOWS, ASPECT_OPTIONS, FENGSHUI_OPTIONS } from './design-flow/state'

import {
  planSource, stepIndex, steps, currentStep, isLastStep,
  floorPlanUrl, floorPlanPath, sceneGraph, floorPlanUpload, uploadedPlanUrl, detectedRooms,
  cadCounts, cadTotalPing, cadExtraRooms, cadPlanResult, cadActiveRoomId, cadRoomStatus,
  cadBatch, cadBatchRunning,
  editPlacements, roomW, roomD, roomTypeForPlan, layoutViewMode, layoutRenderConfig,
  roomType, spaceSizePing, customRoomW, customRoomD,
  furnitureItems, furnitureQty, extraPrompt, fengshuiRules, outputAspect,
  spacePhoto, spacePhotoPath,
  selectedStyle, noStyleReference, styleMethod, styleRefImage,
  styleOptions, styleLoading, styleError,
  styleCandidates, candidatesLoading, candidatesError, candidatesSearched, confirmedStyle, matchedStylePreview,
  styleDemoImages,
  showSuggestions,
  result, loading, loadingMsg, error, submitKey, swappingStyle, styleSwapCache,
  spaceImage, lastGeneratedImage, manualMaskPath, brushSize, eraserSize, drawMode,
  textPrompt, refineCanvasRef, baseImagePreview,
  panoLoading, panoUrl, panoError,
  quotationLoading, quotationError,
  favoriteLoading, favoriteError,
} from './design-flow/state'

import { goStep, nextStep, prevStep, startFlow, resetFlow } from './design-flow/navigation'
import { uploadFile } from './design-flow/common'
import {
  fetchStyleOptions, fetchStyleCandidates, showNextRound, scheduleSearch,
  confirmStyle, clearConfirmedStyle, fetchStyleDemoImages,
} from './design-flow/style'
import {
  submitLayout, useUploadedPlan, handleRoomSelected, onEditorChange, updateFloorPlan,
} from './design-flow/layout'
import { applyToRooms, cancelCadBatch } from './design-flow/cadBatch'
import { submitRoomProgram, handleCadRoomSelected, jumpToCadRoom, abandonCadRoom } from './design-flow/cad'
import { submitPhoto, submit3D, swapStyle, generatePanorama } from './design-flow/render'
import { handleMaskReady, submitRefine, undoRefine, canUndoRefine } from './design-flow/refine'
import { fetchQuotation, toggleFavoriteDesign } from './design-flow/quotation'

export function useDesignFlow() {
  return {
    // 路徑 / 步驟
    planSource, stepIndex, steps, currentStep, isLastStep,
    goStep, nextStep, prevStep, startFlow, resetFlow,
    // 平面圖
    floorPlanUrl, floorPlanPath, sceneGraph, floorPlanUpload, uploadedPlanUrl,
    detectedRooms, handleRoomSelected,
    // CAD 房型生成
    cadCounts, cadTotalPing, cadExtraRooms, cadPlanResult, submitRoomProgram, handleCadRoomSelected,
    cadActiveRoomId, cadRoomStatus, jumpToCadRoom, abandonCadRoom,
    cadBatch, cadBatchRunning, applyToRooms, cancelCadBatch,
    // 佈局
    editPlacements, roomW, roomD, roomTypeForPlan, layoutViewMode, layoutRenderConfig,
    onEditorChange, updateFloorPlan,
    // 空間設定
    roomType, spaceSizePing, customRoomW, customRoomD,
    furnitureItems, furnitureQty, extraPrompt, fengshuiRules, outputAspect,
    // 空間照片
    spacePhoto, spacePhotoPath,
    // 風格
    selectedStyle, noStyleReference, styleMethod, styleRefImage,
    styleOptions, styleLoading, styleError,
    styleCandidates, candidatesLoading, candidatesError, candidatesSearched, confirmedStyle, matchedStylePreview,
    styleDemoImages, fetchStyleDemoImages,
    showSuggestions, fetchStyleOptions, fetchStyleCandidates, showNextRound, scheduleSearch,
    confirmStyle, clearConfirmedStyle,
    // 結果
    result, loading, loadingMsg, error, submitKey, swappingStyle, styleSwapCache, swapStyle,
    // 微調
    spaceImage, lastGeneratedImage, manualMaskPath, brushSize, eraserSize, drawMode,
    textPrompt, refineCanvasRef, baseImagePreview, handleMaskReady,
    // 環景
    panoLoading, panoUrl, panoError, generatePanorama,
    // 估價
    quotationLoading, quotationError, fetchQuotation,
    // 收藏
    favoriteLoading, favoriteError, toggleFavoriteDesign,
    // 動作
    uploadFile, submitLayout, useUploadedPlan, submitPhoto, submit3D, submitRefine, undoRefine, canUndoRefine,
  }
}
