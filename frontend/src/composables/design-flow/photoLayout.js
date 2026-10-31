import { computed } from 'vue'
import { jsonFetch, mediaUrl } from '@/config/api'
import {
  spacePhoto, spacePhotoPath, photoDetection, photoLayoutLoading, photoLayoutError,
  sceneGraph, editPlacements, roomW, roomD, roomTypeForPlan, roomType,
  extraPrompt, floorPlanPath, floorPlanUrl, projectId, spaceInfo,
  photoVersions, photoCurrent, photoBusy, photoStyleId, photoRemovedIds, styleOptions,
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
      text_prompt: extraPrompt.value,
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

// 照片裡還在、而且偵測框對得上目前這張圖的家具（換／刪家具用）
export const editableFurniture = computed(() => {
  if (!currentVersion.value?.aligned) return []
  const removed = new Set(photoRemovedIds.value)
  return (photoDetection.value?.furniture_placements || [])
    .filter(p => Array.isArray(p.image_box) && !removed.has(p.id))
    .map(p => ({ id: p.id, type: p.type, label: furnitureLabel(p.type), box: p.image_box }))
})

function pushVersion(data, label, aligned) {
  photoVersions.value = [...photoVersions.value, {
    path: data.generated_image_path, url: data.generated_image_url || mediaUrl(data.generated_image_path),
    label, aligned, seed: data.render_result?.generation_params?.seed,
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
    photoRemovedIds.value = []
    photoDetection.value = null
    editPlacements.value = []
    spacePhotoPath.value = await uploadFile(file)
    photoVersions.value = [{ path: spacePhotoPath.value, url: spacePhoto.preview || mediaUrl(spacePhotoPath.value), label: '原照片', aligned: true }]
    if (!(await detectPhotoLayout())) throw new Error(photoLayoutError.value || '家具偵測失敗')
  })
}

// 換風格：以目前這張為底整張重生，家具留在原位（後端 restyle 不重排、走照片深度）
export function restylePhoto(styleId) {
  const base = currentVersion.value
  if (!base) return
  const name = styleOptions.value.find(o => o.value === styleId)?.name || styleId
  return runPhotoJob(`套用「${name}」風格中…`, async () => {
    const data = await generate({
      text_prompt: extraPrompt.value.trim() || `${name}風格的室內設計`,
      style_profile_id: styleId,
      initial_image_path: base.path,
      restyle: true,
    })
    photoStyleId.value = styleId
    pushVersion(data, `風格：${name}`, base.aligned)
  })
}

// 移家具：照片原深度清掉舊家具、新位置疊回去整張重生
export function renderPhotoLayout() {
  const det = photoDetection.value
  if (!det || !editPlacements.value.length) return
  return runPhotoJob('依新的家具位置重新生成…', async () => {
    const { baseline, ...sg } = det
    const data = await generate({
      text_prompt: extraPrompt.value.trim(),
      style_profile_id: photoStyleId.value || undefined,
      no_style_reference: !photoStyleId.value,
      initial_image_path: spacePhotoPath.value,
      scene_graph: { ...sg, furniture_placements: editPlacements.value, room_w: roomW.value, room_d: roomD.value },
    })
    pushVersion(data, '新的家具位置', false)
  })
}

// 偵測框外擴一點當遮罩（白＝要改），交給 adjuster 局部重繪
async function boxMask(url, box) {
  const img = await new Promise((resolve, reject) => {
    const im = new Image()   // 只讀尺寸、不畫進 canvas，不需要 CORS
    im.onload = () => resolve(im)
    im.onerror = () => reject(new Error('讀不到目前的圖片'))
    im.src = url
  })
  const w = img.naturalWidth, h = img.naturalHeight
  const c = document.createElement('canvas')
  c.width = w; c.height = h
  const ctx = c.getContext('2d')
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h)
  const [x0, y0, x1, y1] = box
  const pad = 0.03
  ctx.fillStyle = '#fff'
  ctx.fillRect(Math.max(0, x0 - pad) * w, Math.max(0, y0 - pad) * h, (Math.min(1, x1 + pad) - Math.max(0, x0 - pad)) * w, (Math.min(1, y1 + pad) - Math.max(0, y0 - pad)) * h)
  const blob = await new Promise(r => c.toBlob(r, 'image/png'))
  return uploadFile(new File([blob], 'mask.png', { type: 'image/png' }))
}

// 換／刪家具：action = 'remove' | 'replace'；遮罩來自偵測框（item）或使用者畫筆（maskBlob）
function editCurrent({ action, replacement, what, getMaskPath, onDone }) {
  const base = currentVersion.value
  if (!base) return
  const text = action === 'remove'
    ? `移除${what}，用周圍的地板與牆面自然補齊`
    : `把${what}換成${replacement.trim()}`
  return runPhotoJob(action === 'remove' ? `刪除${what}中…` : `把${what}換掉中…`, async () => {
    const data = await generate({
      text_prompt: text,
      initial_image_path: base.path,
      mask_image_path: await getMaskPath(base),
      refine_mode: true,
      no_style_reference: true,
    })
    pushVersion(data, action === 'remove' ? `刪除${what}` : `${what}→${replacement.trim()}`, base.aligned)
    onDone?.()
  })
}

export function editPhotoFurniture(item, action, replacement = '') {
  if (!item) return
  return editCurrent({
    action, replacement, what: item.label,
    getMaskPath: (base) => boxMask(base.url, item.box),
    onDone: () => {
      if (action !== 'remove') return
      photoRemovedIds.value = [...photoRemovedIds.value, item.id]
      editPlacements.value = editPlacements.value.filter(p => p.id !== item.id)
    },
  })
}

export function editPhotoByMask(maskBlob, action, replacement = '') {
  if (!maskBlob) return
  return editCurrent({
    action, replacement, what: '塗抹範圍內的家具',
    getMaskPath: () => uploadFile(new File([maskBlob], 'mask.png', { type: 'image/png' })),
  })
}
