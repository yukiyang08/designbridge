import { watch } from 'vue'
import { jsonFetch } from '@/config/api'
import {
  FENGSHUI_OPTIONS,
  fengshuiEnabled, fengshuiExcluded, fengshuiReport, fengshuiReportLoading, fengshuiLastFix,
  photoAudit, photoAuditLoading, photoAuditError,
  editPlacements, roomW, roomD, roomTypeForPlan, roomGeometry, roomType, cadActiveRoomId,
  spacePhoto, spacePhotoPath,
} from './state'
import { uploadFile } from './common'
import { onEditorChange } from './layout'
import { furnitureLabel } from '@/config/furniture'

/* ══ 規則挑選 ══════════════════════════════════════════════ */

// 自訂房型（「和室」）對不上任何一條時全部視為相關，跟後端 rules_for_room 同邏輯
export function relevantFengshuiOptions(type) {
  const hit = FENGSHUI_OPTIONS.filter(o => o.rooms.includes(type))
  return hit.length ? hit : FENGSHUI_OPTIONS
}

/** 實際要送給後端的規則：關閉時是空的，開啟時 = 房型相關 − 使用者取消的。 */
export function fengshuiRulesFor(type) {
  if (!fengshuiEnabled.value) return []
  return relevantFengshuiOptions(type)
    .map(o => o.value)
    .filter(v => !fengshuiExcluded.value.includes(v))
}

/* ══ 門窗：編輯器格式 → 後端歸一化方框 ═══════════════════════
   編輯器存「哪一邊＋沿邊比例＋公尺寬」，special_constraints 吃的是平面圖座標的方框。
   top/bottom 對應後端的 far/near。 */

const SIDE_TO_WALL = { top: 'far', bottom: 'near', left: 'left', right: 'right' }

export function openingBox(wall, frac, widthM, W, D) {
  if (wall === 'far' || wall === 'near') {
    const w = Math.min(0.9, widthM / W)
    return { x: Math.max(0, Math.min(1 - w, frac - w / 2)), y: wall === 'far' ? 0 : 0.98, w, h: 0.02, wall }
  }
  const h = Math.min(0.9, widthM / D)
  return { x: wall === 'left' ? 0 : 0.98, y: Math.max(0, Math.min(1 - h, frac - h / 2)), w: 0.02, h, wall }
}

export function geometryOpenings(geometry, W, D) {
  if (!geometry) return {}   // 沒有門窗資料：後端用預設門窗推估，報告會註明
  const pick = type => geometry.openings
    .filter(o => o.type === type)
    .map(o => openingBox(SIDE_TO_WALL[o.side], o.frac, o.width, W, D))
  return { doors: pick('door'), windows: pick('window') }
}

const editorOpenings = () => geometryOpenings(roomGeometry.value, roomW.value, roomD.value)

/* ══ 平面圖步驟：即時健檢 ═══════════════════════════════════ */

let auditTimer = null
let auditSeq = 0

export function scheduleFengshuiAudit(delay = 400) {
  clearTimeout(auditTimer)
  auditTimer = setTimeout(runFengshuiAudit, delay)
}

export async function runFengshuiAudit() {
  if (!editPlacements.value.length) { fengshuiReport.value = null; return }
  const seq = ++auditSeq
  fengshuiReportLoading.value = true
  try {
    const res = await jsonFetch('/api/fengshui/audit', {
      placements: editPlacements.value,
      room_w: roomW.value,
      room_d: roomD.value,
      room_type: roomTypeForPlan.value,
      ...editorOpenings(),
      // 關閉時檢查全部相關規則，才算得出「有幾處不符合」的提示
      rules: fengshuiEnabled.value ? fengshuiRulesFor(roomTypeForPlan.value) : undefined,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (seq === auditSeq) fengshuiReport.value = data
  } catch {
    if (seq === auditSeq) fengshuiReport.value = null   // 健檢失敗不擋流程，報告卡不顯示而已
  } finally {
    if (seq === auditSeq) fengshuiReportLoading.value = false
  }
}

const failingOf = report => [
  ...(report?.fengshui?.rules || []).filter(r => r.status === 'fail').map(r => ({ key: r.trigger, label: r.label, offenders: r.offenders })),
  ...(report?.circulation?.issues || []).map(i => ({
    key: i.kind, label: i.kind === 'door_blocked' ? '門口被擋住' : '有家具走不到', offenders: i.offenders,
  })),
]

// 「床　往左 0.8 公尺、往上 0.3 公尺」——平面圖上看得到的方向
function describeMove(before, after) {
  const dx = (after.x - before.x) * roomW.value
  const dy = (after.y - before.y) * roomD.value
  const parts = []
  if (Math.abs(dx) >= 0.05) parts.push(`往${dx > 0 ? '右' : '左'} ${Math.abs(dx).toFixed(1)} 公尺`)
  if (Math.abs(dy) >= 0.05) parts.push(`往${dy > 0 ? '下' : '上'} ${Math.abs(dy).toFixed(1)} 公尺`)
  return { label: furnitureLabel(after.type), text: parts.join('、') || '微調位置' }
}

/** 開啟風水（若還沒開）並把違規家具推開；結果直接寫回編輯器。 */
export async function applyFengshuiFix() {
  fengshuiEnabled.value = true
  const rules = fengshuiRulesFor(roomTypeForPlan.value)
  if (!rules.length || !editPlacements.value.length) return
  const previous = editPlacements.value
  const beforeFailing = failingOf(fengshuiReport.value)
  fengshuiReportLoading.value = true
  try {
    const res = await jsonFetch('/api/fengshui/fix', {
      placements: previous,
      room_w: roomW.value,
      room_d: roomD.value,
      room_type: roomTypeForPlan.value,
      ...editorOpenings(),
      rules,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    // 使用者在等待期間又動了家具，就不拿舊的修正結果蓋掉
    if (editPlacements.value !== previous) return
    const afterFailing = new Set(failingOf(data.report).map(f => f.key))
    const checked = new Set([
      ...(data.report?.fengshui?.rules || []).filter(r => r.status !== 'na').map(r => r.trigger),
      'door_blocked', 'unreachable',
    ])
    const prevById = Object.fromEntries(previous.map(p => [p.id, p]))
    fengshuiLastFix.value = {
      moved: data.moved.length,
      movedIds: data.moved,
      previous,
      beforeOffenders: beforeFailing.flatMap(f => f.offenders),
      resolved: beforeFailing.filter(f => checked.has(f.key) && !afterFailing.has(f.key)).map(f => f.label),
      moves: data.placements.filter(p => data.moved.includes(p.id)).map(p => describeMove(prevById[p.id], p)),
    }
    // 報告不在這裡寫：placements 一變，watch 會重新健檢，避免跟進行中的健檢互相覆蓋
    if (data.moved.length) onEditorChange(data.placements)
    else scheduleFengshuiAudit(0)
  } catch {
    fengshuiLastFix.value = null
  } finally {
    fengshuiReportLoading.value = false
  }
}

// 換房間後，上一次的「復原」已經不是這組家具的了（重新排版在 layout.js 清掉）
watch(cadActiveRoomId, () => { fengshuiLastFix.value = null })

export function undoFengshuiFix() {
  const fix = fengshuiLastFix.value
  if (!fix) return
  fengshuiLastFix.value = null
  onEditorChange(fix.previous)
}

/* ══ 照片健檢 ═════════════════════════════════════════════ */

export async function runPhotoAudit() {
  if (!spacePhoto.file) return
  photoAuditLoading.value = true
  photoAuditError.value = ''
  photoAudit.value = null
  try {
    spacePhotoPath.value = await uploadFile(spacePhoto.file)
    const res = await jsonFetch('/api/fengshui/photo-audit', {
      image_path: spacePhotoPath.value,
      room_type: roomType.value,
    })
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail
      throw new Error(detail || `${res.status}`)
    }
    const data = await res.json()
    photoAudit.value = data
    // 照片路徑裡房型只拿來挑風水規則；AI 認出的房型比預設的「客廳」可靠
    if (data.plan?.room_type) roomType.value = data.plan.room_type
  } catch (e) {
    photoAuditError.value = `健檢失敗：${e.message}`
  } finally {
    photoAuditLoading.value = false
  }
}

/** 使用者改了門的位置（照片看不到門時是猜的）→ 不重打 Gemini，只重算報告。 */
export async function movePhotoDoor(index, wall, frac) {
  const plan = photoAudit.value?.plan
  if (!plan) return
  const doors = plan.doors.map((d, i) => i !== index ? d : {
    ...d, ...openingBox(wall, frac, d.width_m || 0.9, plan.room_w, plan.room_d),
    pos: frac, assumed: false, image_box: wall === d.wall ? d.image_box : null,
  })
  const nextPlan = { ...plan, doors }
  photoAudit.value = { ...photoAudit.value, plan: nextPlan }
  try {
    const res = await jsonFetch('/api/fengshui/audit', {
      placements: plan.placements, room_w: plan.room_w, room_d: plan.room_d,
      room_type: plan.room_type, doors, windows: plan.windows,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const report = await res.json()
    if (photoAudit.value?.plan === nextPlan) photoAudit.value = { ...photoAudit.value, report }
  } catch (e) {
    photoAuditError.value = `重新計算失敗：${e.message}`
  }
}

/** 照片健檢的「幫我改」：開啟風水，並確保這次違規的規則都在套用清單裡。 */
export function adoptPhotoAudit() {
  const failed = (photoAudit.value?.report?.fengshui?.rules || [])
    .filter(r => r.status === 'fail').map(r => r.trigger)
  fengshuiEnabled.value = true
  fengshuiExcluded.value = fengshuiExcluded.value.filter(v => !failed.includes(v))
}
