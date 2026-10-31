import { jsonFetch } from '@/config/api'
import {
  ROOM_TYPE_LABEL, requestState, timers,
  error, loading, loadingMsg, result, submitKey, swappingStyle, styleSwapCache,
  spacePhoto, spacePhotoPath,
  styleRefImage, confirmedStyle, noStyleReference, selectedStyle, styleMethod,
  editPlacements, sceneGraph, floorPlanPath, roomW, roomD,
  extraPrompt, fengshuiRules, outputAspect, roomTypeForPlan, spaceSizePing,
  planSource, cadActiveRoomId, cadRoomStatus, cadRoomSnapshots, cadRendering, cadRenderError, cadRenderTokens, lastGeneratedImage,
  panoLoading, panoUrl, panoError, projectId, spaceInfo,
} from './state'
import { nextStep } from './navigation'
import { uploadFile } from './common'
import { updateFloorPlan } from './layout'
import { snapshotCurrentCadRoom } from './cad'
import { saveProjectSettings } from './projectSync'
import { detectPhotoLayout } from './photoLayout'

// 原圖（submit3D 第一次生成的那張）在 styleSwapCache 裡的固定 key——跟真正的
// style_profile_id 分開存，這樣就算原圖沒套風格（no_style_reference / 風格搜尋落空，
// style_profile_id 是 undefined）也一定留得住，不會因為沒有 style id 可當 key 就存不進去。
export const ORIGINAL_STYLE_KEY = '__original__'

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
    // 結果頁同時放偵測到的佈局、渲染圖、換風格與局部修改；先偵測家具再依偵測佈局生第一張。
    // 偵測失敗就照舊只拿照片生成（不帶 scene_graph）。
    nextStep()
    loadingMsg.value = { title: '偵測照片中的家具', sub: 'AI 辨識家具位置與房間尺寸，約 10–20 秒' }
    const detected = await detectPhotoLayout()
    if (!detected) editPlacements.value = []
    await submit3D()
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
  // 整層逐間設計：渲染要 30–60 秒，這段時間要能切去看別間，所以不佔用全域 loading，
  // 結果回來時依使用者人在哪間決定放哪裡。其他路徑（單間、照片…）維持原本的整頁載入。
  const cadRoomId = planSource.value === 'cad' ? cadActiveRoomId.value : null
  const token = cadRoomId ? (cadRenderTokens[cadRoomId] = (cadRenderTokens[cadRoomId] || 0) + 1) : 0
  const isLatest = () => (cadRoomId ? cadRenderTokens[cadRoomId] === token : requestId === requestState.current)

  // 送出所需的資料要在第一個 await 之前讀完：上傳風格參考圖要等一下，
  // 這段時間使用者可能已經切去別間，全域的家具、描述就不是這間房的了。
  const input = {
    placements: editPlacements.value, sceneGraph: sceneGraph.value, floorPlanPath: floorPlanPath.value,
    roomW: roomW.value, roomD: roomD.value,
    roomTypeForPlan: roomTypeForPlan.value, extraPrompt: extraPrompt.value, spacePhotoPath: spacePhotoPath.value,
    fengshui: fengshuiRules.value, aspect: outputAspect.value, method: styleMethod.value,
    noRef: noStyleReference.value, selected: selectedStyle.value, confirmed: confirmedStyle.value,
    refFile: styleRefImage.file, sizePing: spaceSizePing.value,
  }

  submitKey.value++
  error.value = ''
  result.value = null
  if (cadRoomId) {
    cadRendering.value = { ...cadRendering.value, [cadRoomId]: true }
    const { [cadRoomId]: _e, ...rest } = cadRenderError.value
    cadRenderError.value = rest
  } else {
    loading.value = true
  }
  loadingMsg.value = { title: '生成 3D 渲染圖中', sub: 'AI 將平面配置轉為立體室內透視，通常約 30–60 秒' }
  panoUrl.value = null
  panoError.value = ''
  try {
    let style_reference_image_path
    if (!input.noRef) {
      if (input.refFile) style_reference_image_path = await uploadFile(input.refFile)
      else if (input.confirmed?.image_url) style_reference_image_path = input.confirmed.image_url
    }

    const editedSceneGraph = input.placements.length
      ? {
          ...(input.sceneGraph || {}),
          furniture_placements: input.placements,
          floor_plan_path: input.floorPlanPath || input.sceneGraph?.floor_plan_path,
          // 後端換算 IKEA 商品真實尺寸要用編輯器的房間大小，不然會退回 AI 猜的坪數
          room_w: input.roomW,
          room_d: input.roomD,
        }
      : undefined

    // 跳過排版時沒有 scene_graph、沒有平面圖、也沒有照片，房型與坪數就沒有任何
    // 欄位可以承載（DesignRequest 沒有 room_type / space_size）。折進 text_prompt，
    // 使用者在第一步選的東西才真的會影響生成結果，而不是選了等於沒選。
    const noSpatialInput = !editedSceneGraph && !input.floorPlanPath && !input.spacePhotoPath
    // 有平面圖／scene_graph 的流程（含整層 CAD 逐間設計）同樣沒有欄位承載房型，不寫進描述的話 AI 會自己
    // 猜——實測客餐廳被猜成臥室、沙發畫成床。所以非照片流程一律把房型帶進描述。
    const roomLabel = ROOM_TYPE_LABEL[input.roomTypeForPlan] || ''
    const spacePreamble = noSpatialInput
      ? `${roomLabel}，約 ${input.sizePing} 坪。`
      : (!input.spacePhotoPath && roomLabel ? `${roomLabel}。` : '')

    const res = await jsonFetch('/api/generate', {
      text_prompt:      (spacePreamble + input.extraPrompt).trim(),
      style_profile_id: !input.noRef && input.selected !== 'auto'
        ? input.selected
        : !input.noRef ? input.confirmed?.style_id || undefined : undefined,
      style_reference_image_path,
      no_style_reference: input.noRef,
      refine_mode:        false,
      output_aspect:      input.aspect,
      style_method:       input.method,
      fengshui_rules:     input.fengshui,
      // 上傳照片路徑：把照片當作生成的起始影像
      initial_image_path: input.spacePhotoPath || undefined,
      floor_plan_path:    input.floorPlanPath || undefined,
      scene_graph:        editedSceneGraph,
      project_id:         projectId.value,
      ...spaceInfo(),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (!isLatest()) return
    saveProjectSettings()   // 把這次用的設定存雲端，「繼續編輯」時還原
    const image = data.generated_image_path
      ? { path: data.generated_image_path, url: data.generated_image_url || null }
      : null

    if (cadRoomId && cadActiveRoomId.value !== cadRoomId) {
      // 使用者在等待時已經切去別間：結果存進「那間房」的快照、標成完成，不能動到畫面上目前這間的狀態。
      // 回到那間房時 restoreCadRoomSnapshot 會把它還原出來。
      cadRoomSnapshots.value = {
        ...cadRoomSnapshots.value,
        [cadRoomId]: { ...(cadRoomSnapshots.value[cadRoomId] || {}), result: data, lastGeneratedImage: image },
      }
      cadRoomStatus.value = { ...cadRoomStatus.value, [cadRoomId]: 'done' }
      return
    }

    result.value = data
    // 新的一輪生成（房間/描述可能都變了），舊風格版本快取失效；用這次的結果重新起頭。
    // 原圖一定存進 ORIGINAL_STYLE_KEY（不管有沒有套風格），style_profile_id 另外多存一份
    // 純粹是讓「這個風格已經生成過」的縮圖判斷（swapStyle 的 cache 命中）也認得出原圖本身。
    const styleId = data.style_params?.style_profile_id
    styleSwapCache.value = { [ORIGINAL_STYLE_KEY]: data, ...(styleId ? { [styleId]: data } : {}) }
    if (image) lastGeneratedImage.value = image
    // CAD 多房間流程：這間房的 3D 渲染圖生成完成才算「完成」（縮圖才會標成完成、可以套用到其他房間）。
    if (cadRoomId) {
      cadRoomStatus.value = { ...cadRoomStatus.value, [cadRoomId]: 'done' }
      snapshotCurrentCadRoom()
    }
  } catch (e) {
    if (!isLatest()) return
    if (cadRoomId && cadActiveRoomId.value !== cadRoomId) {
      // 使用者已經離開那間房：不能把錯誤寫到畫面上現在這間，留著，回去時再顯示
      cadRenderError.value = { ...cadRenderError.value, [cadRoomId]: `生成渲染圖失敗：${e.message}` }
    } else {
      error.value = `生成渲染圖失敗：${e.message}`
    }
  } finally {
    if (cadRoomId) {
      if (isLatest()) {
        const { [cadRoomId]: _r, ...rest } = cadRendering.value
        cadRendering.value = rest
      }
    } else if (requestId === requestState.current) {
      loading.value = false
    }
  }
}

/* ══ 一鍵換風格 ═══════════════════════════════════════════
   帶著上次 /api/generate 的完整回應當 plan 送回去（見 api.py 的 plan 欄位），
   讓 requirement/vision/layout 三個節點偵測到已有值而跳過重跑，只有
   layout_and_style_agent 的風格搜尋 + renderer 會重跑。故意不帶 style_params，
   帶了的話 layout_and_style_agent 會直接沿用舊風格、新 style_profile_id 等於沒送。
   text_prompt 在這裡不影響結果：structured_requirement 已經在 plan 裡，
   requirement_analyzer 會整個跳過，不會重讀 text_prompt。

   styleSwapCache 記住這個房間這一輪每個風格生成過的結果：換過的風格再點一次
   不用重打 API，直接換圖；同一個房間裡切來切去的版本都留著，不會互相覆蓋掉。 */

export async function swapStyle(styleId) {
  const prev = result.value
  if (!prev || swappingStyle.value) return

  const cached = styleSwapCache.value[styleId]
  if (cached) {
    result.value = cached
    if (cached.generated_image_path) {
      lastGeneratedImage.value = { path: cached.generated_image_path, url: cached.generated_image_url || null }
    }
    return
  }

  const requestId = ++requestState.current
  error.value = ''
  swappingStyle.value = true
  try {
    const { style_params, ...plan } = prev
    const res = await jsonFetch('/api/generate', {
      text_prompt:       extraPrompt.value.trim(),
      style_profile_id:  styleId,
      output_aspect:      outputAspect.value,
      style_method:       styleMethod.value,
      // 照片流程：輸出比例跟第一張一樣依照片決定，不然換風格會變成預設比例
      initial_image_path: spacePhotoPath.value || undefined,
      plan,
      project_id:         projectId.value,
      ...spaceInfo(),
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (requestId === requestState.current) {
      result.value = data
      styleSwapCache.value = { ...styleSwapCache.value, [data.style_params?.style_profile_id || styleId]: data }
      if (data.generated_image_path) {
        lastGeneratedImage.value = { path: data.generated_image_path, url: data.generated_image_url || null }
      }
    }
  } catch (e) {
    if (requestId === requestState.current) error.value = `換風格失敗：${e.message}`
  } finally {
    if (requestId === requestState.current) swappingStyle.value = false
  }
}

// 換回最一開始生成的那張（不管當初有沒有套風格），純讀快取，不重打 API。
export function restoreOriginal() {
  const cached = styleSwapCache.value[ORIGINAL_STYLE_KEY]
  if (!cached) return
  result.value = cached
  if (cached.generated_image_path) {
    lastGeneratedImage.value = { path: cached.generated_image_path, url: cached.generated_image_url || null }
  }
}

/* ══ Step: 360° 環景 ══════════════════════════════════════ */

export async function generatePanorama() {
  const r = result.value
  if (!r?.task_id || !r?.generated_image_path) return
  const taskId = r.task_id
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
    if (result.value?.task_id !== taskId) return   // 生成途中已經換房間／重新生成，這張環景不屬於現在這張圖
    panoUrl.value = data.room_panorama_url
  } catch (e) {
    panoError.value = e.message
  } finally {
    panoLoading.value = false
  }
}
