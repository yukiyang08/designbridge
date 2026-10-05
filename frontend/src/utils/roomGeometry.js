/**
 * 把整層 CAD 平面圖（/api/generate-room-plan 的回應）裡「屬於某一間房」的牆厚、門、窗，
 * 換成單房間編輯器用的相對資料。後端座標是整層的絕對公尺，門窗中心點落在房間矩形的邊上。
 *
 * 位置存「沿該邊的比例 frac」＋ 絕對寬度 width（公尺）：使用者在編輯器改房間長寬時，
 * 門窗跟著等比例移動，寬度維持真實尺寸。
 *
 * 牆厚跟後端 designbridge/roomplan/constants.py 同步（外牆 20cm / 內牆 10cm）。
 */
export const WALL_EXTERIOR_M = 0.2
export const WALL_INTERIOR_M = 0.1

const EPS = 1e-3   // 後端座標四捨五入到 4 位小數
const near = (a, b) => Math.abs(a - b) < EPS

export function buildRoomGeometry(room, plan) {
  if (!room || !plan) return null
  const { x, y, w, h } = room
  const bw = plan.bounding_w_m, bd = plan.bounding_d_m
  const wallT = {
    top:    near(y, 0)     ? WALL_EXTERIOR_M : WALL_INTERIOR_M,
    bottom: near(y + h, bd) ? WALL_EXTERIOR_M : WALL_INTERIOR_M,
    left:   near(x, 0)     ? WALL_EXTERIOR_M : WALL_INTERIOR_M,
    right:  near(x + w, bw) ? WALL_EXTERIOR_M : WALL_INTERIOR_M,
  }

  const openings = []
  const add = (o, type, extra) => {
    const horiz = o.orientation === 'horizontal'
    const line = horiz ? o.y : o.x
    const side = horiz
      ? (near(line, y) ? 'top' : near(line, y + h) ? 'bottom' : null)
      : (near(line, x) ? 'left' : near(line, x + w) ? 'right' : null)
    if (!side) return
    const frac = horiz ? (o.x - x) / w : (o.y - y) / h
    if (frac <= 0 || frac >= 1) return   // 同一條牆上、但在相鄰房間那一段
    openings.push({ id: o.id, type, side, frac, width: o.width_m, ...extra })
  }
  for (const d of plan.doors || []) {
    if ((d.room_ids || []).includes(room.id)) {
      add(d, 'door', { entry: d.kind === 'entry', swingIn: d.swing_into_room_id === room.id })
    }
  }
  for (const win of plan.windows || []) {
    if (win.room_id === room.id) add(win, 'window', {})
  }
  return { wallT, openings }
}

/**
 * 某一邊的門窗在該邊上切出的區段（公尺），給尺寸鏈用：
 * 牆→開口→牆→開口…→牆。開口超出牆長時夾在 [0, len] 內。
 */
export function sideSegments(geometry, side, len) {
  const ops = (geometry?.openings || [])
    .filter(o => o.side === side)
    .map(o => {
      const c = o.frac * len
      return { type: o.type, a: Math.max(0, c - o.width / 2), b: Math.min(len, c + o.width / 2) }
    })
    .sort((p, q) => p.a - q.a)
  if (!ops.length) return []
  const segs = []
  let cur = 0
  for (const o of ops) {
    if (o.a > cur + 1e-6) segs.push({ type: 'wall', len: o.a - cur })
    segs.push({ type: o.type, len: o.b - o.a })
    cur = Math.max(cur, o.b)
  }
  if (len - cur > 1e-6) segs.push({ type: 'wall', len: len - cur })
  return segs
}

const DOOR_CLEARANCE_M = 0.6   // 不往這間房開的門，門口前仍要留的通道深度

/**
 * 門「會碰到」的範圍（歸一化座標，家具不可進入）：
 *  · 往這間房開的門：方形，邊長 = 門寬，剛好包住 90° 開門弧
 *  · 往隔壁開的門：門口前 60cm 的通道，不然家具堵在門口出不去
 */
export function doorKeepouts(geometry, W, D) {
  return (geometry?.openings || []).filter(o => o.type === 'door').map(o => {
    const horiz = o.side === 'top' || o.side === 'bottom'
    const L = horiz ? W : D
    const a = (o.frac * L - o.width / 2) / L, aw = o.width / L           // 沿牆方向
    const d = Math.min(1, (o.swingIn ? o.width : DOOR_CLEARANCE_M) / (horiz ? D : W))   // 往房內方向
    if (o.side === 'top') return { x: a, y: 0, w: aw, h: d }
    if (o.side === 'bottom') return { x: a, y: 1 - d, w: aw, h: d }
    if (o.side === 'left') return { x: 0, y: a, w: d, h: aw }
    return { x: 1 - d, y: a, w: d, h: aw }
  })
}

const overlap = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
const clamp01 = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

/**
 * 把壓在門範圍裡的家具推到最近的空位（優先不跟別的家具重疊）。沒有可行的位置就維持原樣。
 * 沒有任何改動時回傳同一個陣列（呼叫端可以用 === 判斷要不要更新）。
 * 預設擺法、門被拖動、房間改尺寸、旋轉之後都靠它收斂。
 */
export function settlePlacements(items, keepouts, isFloor) {
  if (!keepouts.length) return items
  const out = items.map(it => ({ ...it }))
  const hitsKeep = (r) => keepouts.some(k => overlap(r, k))
  const hitsItem = (r, id) => out.some(o => o.id !== id && !isFloor(o.type) && overlap(r, o))
  let changed = false
  for (const it of out) {
    if (isFloor(it.type) || !hitsKeep(it)) continue
    // 逐格找離原位最近、不碰任何門範圍的位置（優先也不跟別的家具重疊）
    const STEP = 0.02
    let free = null, clear = null, fd = Infinity, cd = Infinity
    for (let x = 0; x <= 1 - it.w + 1e-9; x += STEP) {
      for (let y = 0; y <= 1 - it.h + 1e-9; y += STEP) {
        const c = { x: Math.min(x, 1 - it.w), y: Math.min(y, 1 - it.h) }
        const r = { ...it, ...c }
        if (hitsKeep(r)) continue
        const d = Math.hypot(c.x - it.x, c.y - it.y)
        if (d < fd) { fd = d; free = c }
        if (d < cd && !hitsItem(r, it.id)) { cd = d; clear = c }
      }
    }
    const best = clear || free
    if (best) { it.x = best.x; it.y = best.y; changed = true }
  }
  return changed ? out : items
}
