// 風水禁忌卡片的平面示意圖：上視、單色線稿，紅色虛線 = 禁忌的視線／衝煞方向。
// 只畫「錯誤擺法」，正確擺法由卡片上的 fix 文字說明。沒有畫圖的規則退回原本的 icon。
// 全是這份檔案內的靜態字串，給 v-html 用，沒有使用者輸入。
const BAD = '#b8433a'
const svg = body =>
  `<svg viewBox="0 0 80 60" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`
const sight = (x1, y1, x2, y2) =>
  `<path d="M${x1} ${y1}V${y2}" stroke="${BAD}" stroke-dasharray="3 3"/>`
// 牆（門缺口在底牆 / 頂牆 x30–50）
const roomDoorBottom = '<path d="M30 54H6V6h68v48H50"/><path d="M50 54V38" stroke-width="1.5"/>'
const roomDoorTop = '<path d="M30 6H6v48h68V6H50"/><path d="M50 6v16" stroke-width="1.5"/>'
const window = (y, color = 'currentColor') =>
  `<path d="M28 ${y}h24M28 ${y + 3}h24" stroke="${color}" stroke-width="1.5"/>`
const bed = '<rect x="31" y="10" width="18" height="26"/><rect x="33" y="12" width="14" height="6" stroke-width="1.5"/>'
const burners = x =>
  `<rect x="${x}" y="8" width="16" height="9"/><circle cx="${x + 4.5}" cy="12.5" r="2.5" stroke-width="1.5"/><circle cx="${x + 11.5}" cy="12.5" r="2.5" stroke-width="1.5"/>`

const room = '<path d="M6 6h68v48H6z"/>'
const mirror = '<path d="M28 7h24" stroke-width="3.5"/>'

export const FENGSHUI_DIAGRAMS = {
  door_not_facing_bed: svg(
    `${roomDoorBottom}<rect x="24" y="20" width="32" height="18"/><rect x="26" y="22" width="6" height="14" stroke-width="1.5"/>` +
    `<path d="M34 52V40M46 52V40" stroke="${BAD}" stroke-dasharray="3 3"/>`),
  mirror_not_facing_bed: svg(
    `${room}${mirror}<rect x="31" y="28" width="18" height="24"/><rect x="33" y="44" width="14" height="6" stroke-width="1.5"/>${sight(40, 11, 40, 26)}`),
  door_not_facing_mirror: svg(
    `${roomDoorBottom}${mirror}${sight(40, 52, 40, 12)}`),
  sofa_not_back_to_window: svg(
    `${room}${window(4, BAD)}<rect x="26" y="14" width="28" height="4" fill="currentColor"/><rect x="26" y="18" width="28" height="10"/>`),
  desk_not_back_to_door: svg(
    `${roomDoorTop}<circle cx="40" cy="24" r="4"/><rect x="28" y="32" width="24" height="10"/>${sight(40, 8, 40, 18)}`),
  desk_not_facing_window: svg(
    `${room}${window(4, BAD)}<rect x="28" y="16" width="24" height="9"/><circle cx="40" cy="33" r="4"/>`),
  stove_not_under_window: svg(
    `${room}${window(4, BAD)}<path d="M6 19h68" stroke-width="1.5"/>${burners(32)}`),
  door_not_facing_toilet: svg(
    `${roomDoorBottom}<rect x="35" y="8" width="10" height="6"/><ellipse cx="40" cy="23" rx="6" ry="8"/>${sight(40, 52, 40, 32)}`),
  bed_not_facing_door: svg(
    `${roomDoorBottom}<rect x="31" y="8" width="18" height="26"/><rect x="33" y="10" width="14" height="6" stroke-width="1.5"/>${sight(40, 52, 40, 36)}`),
  bed_head_not_under_window: svg(
    `<path d="M6 6h68v48H6z"/>${window(4, BAD)}${bed}`),
  door_not_facing_stove: svg(
    `${roomDoorBottom}<path d="M6 17h68" stroke-width="1.5"/>${burners(32)}${sight(40, 52, 40, 19)}`),
  sofa_not_back_to_door: svg(
    `${roomDoorTop}<rect x="26" y="28" width="28" height="4" fill="currentColor"/><rect x="26" y="32" width="28" height="10"/>${sight(40, 8, 40, 26)}`),
  door_not_facing_window: svg(
    `${roomDoorBottom}${window(6)}${sight(40, 52, 40, 12)}`),
  stove_away_from_water: svg(
    `<path d="M6 6h68v48H6z"/><path d="M6 19h68" stroke-width="1.5"/>${burners(10)}<rect x="30" y="8" width="16" height="9"/><rect x="33" y="10" width="10" height="5" rx="2" stroke-width="1.5"/><path d="M24 26l6 6m0-6l-6 6" stroke="${BAD}"/>`),
}
