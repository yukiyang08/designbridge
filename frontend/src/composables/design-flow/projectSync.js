import { authFetch, jsonFetch } from '@/config/api'
import {
  planSource, projectId, cadPlanResult, cadRoomStatus, cadRoomSnapshots, cadOverview, openingEdits,
  extraPrompt, outputAspect, fengshuiRules, selectedStyle, noStyleReference, styleMethod, confirmedStyle,
  CAD_ROOM_TYPE_TO_EDITOR, saveDraft,
} from './state'
import { resetFlow } from './navigation'
import { handleCadRoomSelected } from './cad'

/* ══ 專案存雲端：寫回設定 / 從「我的設計」還原 ═══════════════
   正本在 Supabase（projects / project_spaces / designs + Storage）。每次生成完成把「設定」寫回去
   （空間狀態、最新擺放由後端在 /api/generate 時順手更新）；還原時整層平面圖、各房間結果都從 GET 取。
   目前只還原整層（cad）設計。 */

// 失敗不影響流程：頂多下次還原時設定回到預設
export function saveProjectSettings() {
  if (!projectId.value) return
  jsonFetch(`/api/projects/${projectId.value}/state`, {
    plan_source: planSource.value,
    settings: {
      extraPrompt: extraPrompt.value, outputAspect: outputAspect.value, fengshuiRules: fengshuiRules.value,
      selectedStyle: selectedStyle.value, noStyleReference: noStyleReference.value,
      styleMethod: styleMethod.value, confirmedStyle: confirmedStyle.value,
    },
  }, 'PUT').catch(() => {})
}

export async function restoreProject(id) {
  const res = await authFetch(`/api/projects/${encodeURIComponent(id)}`)
  if (!res.ok) throw new Error(res.status === 404 ? '找不到這個設計' : `載入失敗（${res.status}）`)
  const data = await res.json()
  if (data.plan_source !== 'cad' || !data.cad_plan || !data.cad_svg_markup) {
    throw new Error('目前只能繼續編輯整層設計')
  }

  const { opening_edits, ...plan } = data.cad_plan
  const rooms = plan.rooms || []
  const snapshots = {}
  const status = {}
  for (const sp of data.spaces) {
    const room = rooms.find(r => r.id === sp.space_id)
    const r = sp.render
    if (!room || !r) continue   // 沒有生成過的房間視為還沒開始
    snapshots[room.id] = {
      roomW: room.w, roomD: room.h,
      roomTypeForPlan: CAD_ROOM_TYPE_TO_EDITOR[room.room_type] || 'living_room',
      editPlacements: sp.placements || r.scene_graph?.furniture_placements || [],
      floorPlanPath: r.scene_graph?.floor_plan_path || '', floorPlanUrl: r.floor_plan_url || '',
      sceneGraph: null, layoutRenderConfig: null,
      // 紀錄的欄位名跟 /api/generate 回應大致相同；換風格要的 seed 在 render_result.generation_params
      result: { ...r, quotation_result: r.quotation || null, render_result: { generation_params: r.generation_params || {} } },
      lastGeneratedImage: r.generated_image_path
        ? { path: r.generated_image_path, url: r.generated_image_url || null } : null,
      panoUrl: sp.pano_url || null,
    }
    status[room.id] = 'done'
  }
  const first = rooms.find(r => status[r.id])
  if (!first) throw new Error('這個設計還沒有完成的房間')

  resetFlow()
  planSource.value = 'cad'
  projectId.value = data.id
  cadPlanResult.value = { ...plan, svg_markup: data.cad_svg_markup }
  openingEdits.value = opening_edits || {}
  cadRoomSnapshots.value = snapshots
  cadRoomStatus.value = status

  const s = data.settings || {}
  const sample = snapshots[first.id].result
  const label = rooms.map(r => `${r.label_zh}。`).find(p => (sample.text_prompt || '').startsWith(p))   // 批次生成的描述前面有「房名。」
  extraPrompt.value = s.extraPrompt ?? (sample.text_prompt || '').slice(label?.length || 0)
  outputAspect.value = s.outputAspect || 'auto'
  fengshuiRules.value = s.fengshuiRules || []
  selectedStyle.value = s.selectedStyle || sample.style_profile_id || 'auto'
  noStyleReference.value = s.noStyleReference ?? false
  styleMethod.value = s.styleMethod || sample.style_method || 'ai_analysis'
  confirmedStyle.value = s.confirmedStyle || null

  saveDraft()   // 路由守衛靠草稿判斷能不能進 /studio
  await handleCadRoomSelected(first)   // 還原那間房的快照、落在結果頁
  cadOverview.value = true             // 再切到整層總覽（handleCadRoomSelected 會把它關掉）
}
