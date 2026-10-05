import { jsonFetch } from '@/config/api'
import {
  CAD_ROOM_TYPE_TO_EDITOR, cadDefaultPlacements, FENGSHUI_OPTIONS,
  error, result, extraPrompt, outputAspect, styleMethod, fengshuiRules,
  styleRefImage, confirmedStyle, noStyleReference, selectedStyle,
  cadPlanResult, cadRoomStatus, cadRoomSnapshots, cadBatch, cadBatchRunning,
} from './state'
import { uploadFile } from './common'

/* ══ 把目前這間房的設定套用到其他房間，一次生成 ═══════════════
   入口：渲染完成頁的「套用到其他房間」（ApplyToRooms.vue）。

   每間房的流程跟互動式一樣：預設家具 → /api/render-floor-plan 取底圖 → /api/generate。
   不碰 result / editPlacements 這些「目前這間房」的全域狀態，所以批次進行中使用者還能
   繼續看、改手上這一間。完成後直接寫進 cadRoomSnapshots + cadRoomStatus，縮圖、還原、
   選房頁都不用另外同步。

   風格一致性：除了送出跟目前這間房相同的風格輸入（風格 id / 參考圖），還把它回傳的
   style_params 用 plan 帶過去——後端看到已有 style_params 就不會重新搜尋風格
   （layout_and_style.py），每間房用同一組色彩/材質。故意不帶 plan 的其他欄位，
   尤其是 generated_image_path：後端會把它當 img2img 起始圖，每間房都會長得像這一間。
   ponytail: 一致性只靠共用 style_params，渲染 seed 是隨機的（render_backends.py）；
   不夠一致時，升級路徑是讓後端接受固定 seed。 */

const CONCURRENCY = 2   // ponytail: 固定 2 條；後端是本機 GPU 時可能要降到 1

let currentRun = null   // { cancelled, controller }

const setBatch = (id, patch) => { cadBatch.value = { ...cadBatch.value, [id]: { ...cadBatch.value[id], ...patch } } }
const clearBatch = (id) => { const { [id]: _, ...rest } = cadBatch.value; cadBatch.value = rest }

async function post(path, body, run) {
  const res = await jsonFetch(path, body, 'POST', run.controller.signal)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `${res.status}`)
  }
  return res.json()
}

// 跟 render.js 的 submit3D 同一套風格輸入規則，在批次開始時定下來，所有房間共用
async function buildBase() {
  let style_reference_image_path
  if (!noStyleReference.value) {
    if (styleRefImage.file) style_reference_image_path = await uploadFile(styleRefImage.file)
    else if (confirmedStyle.value?.image_url) style_reference_image_path = confirmedStyle.value.image_url
  }
  return {
    prompt: extraPrompt.value.trim(),
    style_profile_id: !noStyleReference.value && selectedStyle.value !== 'auto'
      ? selectedStyle.value
      : !noStyleReference.value ? confirmedStyle.value?.style_id || undefined : undefined,
    style_reference_image_path,
    no_style_reference: noStyleReference.value,
    output_aspect: outputAspect.value,
    style_method: styleMethod.value,
    fengshui: [...fengshuiRules.value],
    style_params: result.value?.style_params || null,
  }
}

async function renderOne(room, base, run) {
  const editorType = CAD_ROOM_TYPE_TO_EDITOR[room.room_type] || 'living_room'
  const placements = cadDefaultPlacements(editorType, room.w, room.h)

  const fp = await post('/api/render-floor-plan', {
    furniture_placements: placements, room_w: room.w, room_d: room.h, room_type: editorType,
  }, run)

  const data = await post('/api/generate', {
    // 後端沒有房型欄位，不加的話臥室可能被畫成客廳
    text_prompt: `${room.label_zh}。${base.prompt}`.trim(),
    style_profile_id: base.style_profile_id,
    style_reference_image_path: base.style_reference_image_path,
    no_style_reference: base.no_style_reference,
    refine_mode: false,
    output_aspect: base.output_aspect,
    style_method: base.style_method,
    // 風水規則跟房型有關，客廳的禁忌套到臥室沒有意義
    fengshui_rules: base.fengshui.filter(v => FENGSHUI_OPTIONS.find(o => o.value === v)?.rooms.includes(editorType)),
    floor_plan_path: fp.floor_plan_path || undefined,
    scene_graph: placements.length
      ? { furniture_placements: placements, floor_plan_path: fp.floor_plan_path }
      : undefined,
    plan: base.style_params ? { style_params: base.style_params } : undefined,
  }, run)

  if (run.cancelled) return
  cadRoomSnapshots.value = {
    ...cadRoomSnapshots.value,
    [room.id]: {
      roomW: room.w, roomD: room.h, roomTypeForPlan: editorType,
      editPlacements: placements,
      floorPlanPath: fp.floor_plan_path || '', floorPlanUrl: fp.floor_plan_url || '',
      sceneGraph: null, layoutRenderConfig: null,
      result: data,
      lastGeneratedImage: data.generated_image_path
        ? { path: data.generated_image_path, url: data.generated_image_url || null }
        : null,
    },
  }
  cadRoomStatus.value = { ...cadRoomStatus.value, [room.id]: 'done' }
  clearBatch(room.id)
}

export async function applyToRooms(roomIds) {
  if (cadBatchRunning.value) return
  const rooms = (cadPlanResult.value?.rooms || []).filter(r => roomIds.includes(r.id))
  if (!rooms.length) return

  error.value = ''
  cadBatchRunning.value = true
  const run = { cancelled: false, controller: new AbortController() }
  currentRun = run

  try {
    const base = await buildBase()
    if (run.cancelled) return
    cadBatch.value = { ...cadBatch.value, ...Object.fromEntries(rooms.map(r => [r.id, { status: 'queued' }])) }

    const queue = [...rooms]
    const worker = async () => {
      while (!run.cancelled) {
        const room = queue.shift()
        if (!room) return
        setBatch(room.id, { status: 'running', error: '' })
        try {
          await renderOne(room, base, run)
        } catch (e) {
          if (run.cancelled) return
          setBatch(room.id, { status: 'failed', error: e.message || '生成失敗' })
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, rooms.length) }, worker))
  } catch (e) {
    if (!run.cancelled) error.value = `套用到其他房間失敗：${e.message}`
  } finally {
    if (currentRun === run) { currentRun = null; cadBatchRunning.value = false }
  }
}

// 只是前端不再等：已經送出的請求後端還是會跑完（取消不了正在算的那張圖）。
export function cancelCadBatch() {
  if (currentRun) { currentRun.cancelled = true; currentRun.controller.abort(); currentRun = null }
  cadBatch.value = {}
  cadBatchRunning.value = false
}
