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
