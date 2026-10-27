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
 *  - fengshui.js    風水規則挑選、平面圖健檢／一鍵調整、照片健檢
 *
 * 這裡只做組裝，不放邏輯——拆檔前後 useDesignFlow() 回傳的形狀完全一致，
 * 呼叫端（各 Step 元件）不用改。
 */

export { STEP_FLOWS, ASPECT_OPTIONS, FENGSHUI_OPTIONS, FENGSHUI_GROUPS } from './design-flow/state'
export { relevantFengshuiOptions } from './design-flow/fengshui'
export { ORIGINAL_STYLE_KEY } from './design-flow/render'

import {
  planSource, stepIndex, steps, currentStep, isLastStep,
  floorPlanUrl, floorPlanPath, sceneGraph, floorPlanUpload, uploadedPlanUrl, detectedRooms, planParseIssue,
  cadCounts, cadTotalPing, cadRoomW, cadRoomD, cadExtraRooms, cadPlanResult, cadActiveRoomId, cadRoomStatus, cadRendering,
  cadBatch, cadBatchRunning, cadRoomSnapshots, cadOverview, cadQuoting,
  editPlacements, roomW, roomD, roomTypeForPlan, layoutViewMode, layoutRenderConfig,
  roomType, spaceSizePing, customRoomW, customRoomD,
  furnitureItems, furnitureQty, extraPrompt, fengshuiEnabled, fengshuiExcluded, fengshuiRules, outputAspect,
  spacePhoto, spacePhotoPath,
  fengshuiReport, fengshuiReportLoading, fengshuiLastFix, photoAudit, photoAuditLoading, photoAuditError,
  selectedStyle, noStyleReference, styleMethod, styleRefImage,
  styleOptions, styleLoading, styleError,
  styleCandidates, candidatesLoading, candidatesError, candidatesSearched, confirmedStyle, matchedStylePreview,
  styleDemoImages,
  showSuggestions,
  result, loading, loadingMsg, error, submitKey, swappingStyle, styleSwapCache,
  roomGeometry, openingEdits,
  spaceImage, lastGeneratedImage, manualMaskPath, brushSize, eraserSize, drawMode,
  textPrompt, refineCanvasRef, baseImagePreview,
  panoLoading, panoUrl, panoError,
  quotationLoading, quotationError,
} from './design-flow/state'

import { goStep, nextStep, prevStep, startFlow, resetFlow } from './design-flow/navigation'
import { uploadFile } from './design-flow/common'
import {
  fetchStyleOptions, fetchStyleCandidates, showNextRound, scheduleSearch,
  confirmStyle, clearConfirmedStyle, fetchStyleDemoImages,
} from './design-flow/style'
import {
  submitLayout, useUploadedPlan, handleRoomSelected, onEditorChange, updateFloorPlan,
  retryPlanParse, parseAsSingleRoom, continueWithoutFurniture,
} from './design-flow/layout'
import { applyToRooms, cancelCadBatch } from './design-flow/cadBatch'
import { submitRoomProgram, rescaleUploadedPlan, fetchRoomPlan, handleCadRoomSelected, jumpToCadRoom, abandonCadRoom, setOpeningEdit } from './design-flow/cad'
import { submitPhoto, submit3D, swapStyle, restoreOriginal, generatePanorama } from './design-flow/render'
import { handleMaskReady, submitRefine, undoRefine, canUndoRefine, refining } from './design-flow/refine'
import { fetchQuotation, quoteRooms } from './design-flow/quotation'
import { restoreProject } from './design-flow/projectSync'
import {
  fengshuiRulesFor, scheduleFengshuiAudit, applyFengshuiFix, undoFengshuiFix,
  runPhotoAudit, movePhotoDoor, adoptPhotoAudit,
} from './design-flow/fengshui'

export function useDesignFlow() {
  return {
    // 路徑 / 步驟
    planSource, stepIndex, steps, currentStep, isLastStep,
    goStep, nextStep, prevStep, startFlow, resetFlow,
    // 平面圖
    floorPlanUrl, floorPlanPath, sceneGraph, floorPlanUpload, uploadedPlanUrl,
    detectedRooms, handleRoomSelected,
    planParseIssue, retryPlanParse, parseAsSingleRoom, continueWithoutFurniture,
    // CAD 房型生成
    cadCounts, cadTotalPing, cadRoomW, cadRoomD, cadExtraRooms, cadPlanResult, submitRoomProgram, rescaleUploadedPlan, fetchRoomPlan, handleCadRoomSelected,
    cadActiveRoomId, cadRoomStatus, jumpToCadRoom, abandonCadRoom,
    cadBatch, cadBatchRunning, cadRoomSnapshots, cadRendering, applyToRooms, cancelCadBatch,
    cadOverview, cadQuoting, quoteRooms, restoreProject,
    // 佈局
    editPlacements, roomW, roomD, roomTypeForPlan, roomGeometry, setOpeningEdit, layoutViewMode, layoutRenderConfig,
    onEditorChange, updateFloorPlan,
    // 空間設定
    roomType, spaceSizePing, customRoomW, customRoomD,
    furnitureItems, furnitureQty, extraPrompt, outputAspect,
    // 空間照片
    spacePhoto, spacePhotoPath,
    // 風水＋動線健檢
    fengshuiEnabled, fengshuiExcluded, fengshuiRules, fengshuiRulesFor,
    fengshuiReport, fengshuiReportLoading, fengshuiLastFix, scheduleFengshuiAudit, applyFengshuiFix, undoFengshuiFix,
    photoAudit, photoAuditLoading, photoAuditError, runPhotoAudit, movePhotoDoor, adoptPhotoAudit,
    // 風格
    selectedStyle, noStyleReference, styleMethod, styleRefImage,
    styleOptions, styleLoading, styleError,
    styleCandidates, candidatesLoading, candidatesError, candidatesSearched, confirmedStyle, matchedStylePreview,
    styleDemoImages, fetchStyleDemoImages,
    showSuggestions, fetchStyleOptions, fetchStyleCandidates, showNextRound, scheduleSearch,
    confirmStyle, clearConfirmedStyle,
    // 結果
    result, loading, loadingMsg, error, submitKey, swappingStyle, styleSwapCache, swapStyle, restoreOriginal,
    // 微調
    spaceImage, lastGeneratedImage, manualMaskPath, brushSize, eraserSize, drawMode,
    textPrompt, refineCanvasRef, baseImagePreview, handleMaskReady,
    // 環景
    panoLoading, panoUrl, panoError, generatePanorama,
    // 估價
    quotationLoading, quotationError, fetchQuotation,
    // 動作
    uploadFile, submitLayout, useUploadedPlan, submitPhoto, submit3D, submitRefine, undoRefine, canUndoRefine, refining,
  }
}
