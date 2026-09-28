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

export { STEP_FLOWS, ASPECT_OPTIONS, FAMILY_OPTIONS, FENGSHUI_OPTIONS } from './design-flow/state'

import {
  planSource, stepIndex, steps, currentStep, isLastStep,
  floorPlanUrl, floorPlanPath, sceneGraph, floorPlanUpload, uploadedPlanUrl, detectedRooms,
  cadCounts, cadTotalPing, cadPlanResult, cadActiveRoomId, cadRoomStatus,
  editPlacements, roomW, roomD, roomTypeForPlan, layoutViewMode, layoutRenderConfig,
  roomType, spaceSizePing, customRoomW, customRoomD,
  furnitureItems, furnitureQty, extraPrompt, familyNeeds, fengshuiRules, outputAspect,
  spacePhoto, spacePhotoPath,
  selectedStyle, noStyleReference, styleMethod, styleRefImage,
  styleOptions, styleLoading, styleError,
  styleCandidates, candidatesLoading, candidatesSearched, confirmedStyle, matchedStylePreview,
  showSuggestions,
  result, loading, loadingMsg, error, submitKey,
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
  confirmStyle, clearConfirmedStyle,
} from './design-flow/style'
import {
  submitLayout, useUploadedPlan, handleRoomSelected, onEditorChange, updateFloorPlan,
} from './design-flow/layout'
import { submitRoomProgram, handleCadRoomSelected, jumpToCadRoom } from './design-flow/cad'
import { submitPhoto, submit3D, generatePanorama } from './design-flow/render'
import { handleMaskReady, submitRefine } from './design-flow/refine'
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
    cadCounts, cadTotalPing, cadPlanResult, submitRoomProgram, handleCadRoomSelected,
    cadActiveRoomId, cadRoomStatus, jumpToCadRoom,
    // 佈局
    editPlacements, roomW, roomD, roomTypeForPlan, layoutViewMode, layoutRenderConfig,
    onEditorChange, updateFloorPlan,
    // 空間設定
    roomType, spaceSizePing, customRoomW, customRoomD,
    furnitureItems, furnitureQty, extraPrompt, familyNeeds, fengshuiRules, outputAspect,
    // 空間照片
    spacePhoto, spacePhotoPath,
    // 風格
    selectedStyle, noStyleReference, styleMethod, styleRefImage,
    styleOptions, styleLoading, styleError,
    styleCandidates, candidatesLoading, candidatesSearched, confirmedStyle, matchedStylePreview,
    showSuggestions, fetchStyleOptions, fetchStyleCandidates, showNextRound, scheduleSearch,
    confirmStyle, clearConfirmedStyle,
    // 結果
    result, loading, loadingMsg, error, submitKey,
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
    uploadFile, submitLayout, useUploadedPlan, submitPhoto, submit3D, submitRefine,
  }
}
