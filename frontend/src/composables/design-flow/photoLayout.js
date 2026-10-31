import { computed } from 'vue'
import { jsonFetch, mediaUrl } from '@/config/api'
import {
  spacePhoto, spacePhotoPath, photoDetection, photoLayoutLoading, photoLayoutError,
  sceneGraph, editPlacements, roomW, roomD, roomTypeForPlan, roomType,
  floorPlanPath, floorPlanUrl, projectId, spaceInfo,
  photoVersions, photoCurrent, photoBusy, photoStyleId, photoStylePrompt, photoQuoting, styleOptions,
} from './state'
import { fengshuiRulesFor } from './fengshui'
import { uploadFile } from './common'
import { furnitureLabel } from '@/config/furniture'
import { settlePlacements } from '@/utils/roomGeometry'

/* ══ 照片入口：偵測家具 → 編輯／自動重排 ════════════════════
   sceneGraph 帶 source:'photo'，後端據此把改過的佈局疊回照片深度（見 projected_depth.reproject_scene_graph）。 */

const toEditable = (list) => (list || []).map((p, i) => ({
  id: p.id || `item_${i}`, type: p.type, x: p.x, y: p.y, w: p.w, h: p.h, rotation: p.rotation || 0,
}))

// 編輯器掛載時會把重疊或出界的家具推開；先在這裡做同一件事，偵測基準才不會一打開就被標成「已移動」
const clamp01 = (p) => {
  const w = Math.min(p.w, 1), h = Math.min(p.h, 1)
  return { ...p, w, h, x: Math.max(0, Math.min(1 - w, p.x)), y: Math.max(0, Math.min(1 - h, p.y)) }
}
const settled = (list) => settlePlacements(toEditable(list).map(clamp01), [])

async function errorDetail(res) {
  return (await res.json().catch(() => ({}))).detail || `${res.status}`
}

export async function detectPhotoLayout() {
  if (!spacePhotoPath.value) return false
  photoLayoutLoading.value = true
  photoLayoutError.value = ''
  try {
    const res = await jsonFetch('/api/photo-layout', { image_path: spacePhotoPath.value })
    if (!res.ok) throw new Error(await errorDetail(res))
    const data = await res.json()
    const sg = data.scene_graph
    const baseline = settled(sg.furniture_placements)
    photoDetection.value = { ...sg, baseline }
    sceneGraph.value = sg
    editPlacements.value = baseline
    roomW.value = sg.room_w
    roomD.value = sg.room_d
    roomTypeForPlan.value = sg.room_type
    roomType.value = sg.room_type
    // 照片流程不畫平面圖，清掉其他路徑殘留的
    floorPlanPath.value = ''
    floorPlanUrl.value = ''
    return true
  } catch (e) {
    photoLayoutError.value = `家具偵測失敗：${e.message}`
    return false
  } finally {
    photoLayoutLoading.value = false
  }
}

export function resetPhotoLayout() {
  if (photoDetection.value) editPlacements.value = photoDetection.value.baseline
}

// 同一組家具交給 layout agent 重排，門窗用照片偵測到的
export async function autoRelayoutPhoto() {
  const det = photoDetection.value
  if (!det || photoLayoutLoading.value) return
  photoLayoutLoading.value = true
  photoLayoutError.value = ''
  try {
    const res = await jsonFetch('/api/generate-layout', {
      room_type: roomTypeForPlan.value,
      room_w: roomW.value,
      room_d: roomD.value,
      furniture_list: editPlacements.value.map(p => p.type),
      text_prompt: photoStylePrompt.value,
      fengshui_rules: fengshuiRulesFor(roomTypeForPlan.value),
      doors: det.doors,
      windows: det.windows,
    })
    if (!res.ok) throw new Error(await errorDetail(res))
    const data = await res.json()
    const next = toEditable(data.scene_graph?.furniture_placements)
    if (!next.length) throw new Error('沒有排出任何家具')
    // layout agent 會重新編 id；同類型依序對回原本的家具，照片上的框才知道是誰被移動
    const pool = editPlacements.value.map(p => ({ id: p.id, type: p.type }))
    editPlacements.value = next.map(p => {
      const i = pool.findIndex(o => o.type === p.type)
      return i < 0 ? p : { ...p, id: pool.splice(i, 1)[0].id }
    })
  } catch (e) {
    photoLayoutError.value = `自動重排失敗：${e.message}`
  } finally {
    photoLayoutLoading.value = false
  }
}


/* ══ 照片工作台（租屋族入口）═══════════════════════════════
   每個動作都以「目前選中的版本」為底圖產生新版本，不覆蓋舊的，使用者可以隨時切回比較。 */

export const currentVersion = computed(() => photoVersions.value[photoCurrent.value] || null)

// 偵測框對得上目前這張圖的家具（快速圈選用）
export const editableFurniture = computed(() => {
  if (!currentVersion.value?.aligned) return []
  return (photoDetection.value?.furniture_placements || [])
    .filter(p => Array.isArray(p.image_box))
    .map(p => ({ id: p.id, type: p.type, label: furnitureLabel(p.type), box: p.image_box }))
})

function pushVersion(data, label, aligned, extra = {}) {
  photoVersions.value = [...photoVersions.value, {
    path: data.generated_image_path, url: data.generated_image_url || mediaUrl(data.generated_image_path),
    label, aligned, seed: data.render_result?.generation_params?.seed, ...extra,
  }]
  photoCurrent.value = photoVersions.value.length - 1
}

async function runPhotoJob(message, fn) {
  if (photoBusy.value) return
  photoBusy.value = message
  photoLayoutError.value = ''
  try {
    await fn()
  } catch (e) {
    photoLayoutError.value = e.message
  } finally {
    photoBusy.value = ''
  }
}

async function generate(payload) {
  const res = await jsonFetch('/api/generate', { output_aspect: 'auto', project_id: projectId.value, ...spaceInfo(), ...payload })
  if (!res.ok) throw new Error(await errorDetail(res))
  const data = await res.json()
  if (!data.generated_image_path) throw new Error('沒有產生圖片')
  // 修圖服務全失敗時後端回原圖副本，不能當成功
  if (data.render_result?.generation_params?.backend === 'placeholder' || data.backend === 'placeholder') {
    throw new Error('AI 服務沒有產生新圖，請稍後再試')
  }
  return data
}

// 上傳 → 偵測家具；換照片就整個重來
export function uploadPhoto(file) {
  return runPhotoJob('上傳並偵測照片中的家具…', async () => {
    photoVersions.value = []
    photoCurrent.value = 0
    photoDetection.value = null
    editPlacements.value = []
    spacePhotoPath.value = await uploadFile(file)
    photoVersions.value = [{ path: spacePhotoPath.value, url: spacePhoto.preview || mediaUrl(spacePhotoPath.value), label: '原照片', aligned: true }]
    if (!(await detectPhotoLayout())) throw new Error(photoLayoutError.value || '家具偵測失敗')
  })
}

// 換風格：以目前這張為底整張重生，家具留在原位（後端 restyle 不重排、走照片深度）。
// 同一張底圖換過的風格直接切過去，不重打 API（跟其他入口的一鍵換風格一樣）
export const styleVersionIndex = (styleId) => {
  const basePath = currentVersion.value?.basePath || currentVersion.value?.path
  return photoVersions.value.findIndex(v => v.styleId === styleId && v.basePath === basePath)
}

// styleId 為空：只用使用者打的描述（例如「地中海風」）找風格
export function restylePhoto(styleId = '') {
  const text = photoStylePrompt.value.trim()
  if (styleId && !text) {
    const cached = styleVersionIndex(styleId)
    if (cached >= 0) { photoCurrent.value = cached; photoStyleId.value = styleId; return }
  }
  const base = currentVersion.value
  if (!base || (!styleId && !text)) return
  const basePath = base.basePath || base.path
  const name = styleId ? (styleOptions.value.find(o => o.value === styleId)?.name || styleId) : text
  return runPhotoJob(`套用「${name.slice(0, 12)}」風格中…`, async () => {
    const data = await generate({
      text_prompt: text || `${name}風格的室內設計`,
      style_profile_id: styleId || undefined,
      initial_image_path: base.path,
      restyle: true,
    })
    photoStyleId.value = styleId || data.style_params?.style_profile_id || ''
    // 有自己打描述的版本不進快取，免得下次點同一張卡片拿到的是別的描述
    pushVersion(data, `風格：${name.slice(0, 8)}`, base.aligned, text ? {} : { styleId, basePath })
  })
}

// 移家具：在原圖上把家具挖掉、補背景、貼到新位置，房間其他部分不重新生成。
// 底圖用目前這一版（家具還在原位時）或原照片，位移一律跟偵測基準比
export function renderPhotoLayout() {
  const det = photoDetection.value
  if (!det) return
  const base = currentVersion.value?.aligned ? currentVersion.value : photoVersions.value[0]
  return runPhotoJob('在原圖上搬動家具…', async () => {
    const res = await jsonFetch('/api/photo-move', {
      photo_path: spacePhotoPath.value,
      image_path: base.path,
      detected: det.furniture_placements,
      baseline: det.baseline,
      placements: editPlacements.value,
    })
    if (!res.ok) throw new Error(await errorDetail(res))
    pushVersion(await res.json(), '新的家具位置', false)
  })
}

// 在圖上拖曳家具（FurnitureMover，跟結果頁同一套）的結果收成新版本；家具位置變了，偵測框不再對得上
export function adoptPhotoMove(data) {
  pushVersion(data, '移動家具', false)
}

// 細節調整：塗抹範圍＋一句描述（刪除、換成什麼都寫在描述裡），跟其他入口的圖上編輯一樣
export function refinePhoto(maskBlob, text) {
  const base = currentVersion.value
  if (!base || !maskBlob || !text.trim()) return
  return runPhotoJob('AI 重繪中，只會改動塗抹的區域…', async () => {
    const mask_image_path = await uploadFile(new File([maskBlob], 'mask.png', { type: 'image/png' }))
    const data = await generate({
      text_prompt: text.trim(),
      initial_image_path: base.path,
      mask_image_path,
      refine_mode: true,
      no_style_reference: true,
    })
    pushVersion(data, text.trim().slice(0, 12), base.aligned)
  })
}

// 家具估價清單：跟結果頁同一支 /api/quotation，報價記在各版本上，切回舊版本不用重估
export async function quotePhoto(force = false) {
  const v = currentVersion.value
  if (!v || photoQuoting.value || (v.quotation && !force)) return
  photoQuoting.value = true
  const idx = photoCurrent.value
  const save = (patch) => {
    photoVersions.value = photoVersions.value.map((x, i) => (i === idx ? { ...x, ...patch } : x))
  }
  save({ quoteError: '' })
  try {
    const res = await jsonFetch('/api/quotation', {
      image_path: v.path,
      structured_requirement: null,
      selected_furniture: [],
      style_profile_id: v.styleId || photoStyleId.value || null,
    })
    if (!res.ok) throw new Error(await errorDetail(res))
    const data = await res.json()
    if (!data?.furniture_list?.length) throw new Error('沒有辨識到畫面中的家具')
    save({ quotation: data })
  } catch (e) {
    save({ quoteError: `估價失敗：${e.message}` })
  } finally {
    photoQuoting.value = false
  }
}
