const SVG_NS = 'http://www.w3.org/2000/svg'

// 在整層平面圖某間房（.room-rect）的地板上畫家具，取代後端畫的預設符號。
// 只用純色 rect：縮圖這麼小，細節符號看不出差異，不必在前端重做一份後端的家具繪製。
export function drawRoomFurniture(g, placements) {
  const floor = g.querySelector('.room-floor')
  if (!floor) return
  const fx = parseFloat(floor.getAttribute('x'))
  const fy = parseFloat(floor.getAttribute('y'))
  const fw = parseFloat(floor.getAttribute('width'))
  const fh = parseFloat(floor.getAttribute('height'))
  if (!Number.isFinite(fx) || !Number.isFinite(fw)) return

  g.querySelector('.room-furniture')?.remove()
  const doc = g.ownerDocument
  const group = doc.createElementNS(SVG_NS, 'g')
  group.setAttribute('class', 'room-furniture')
  for (const p of placements) {
    const x = fx + (p.x || 0) * fw
    const y = fy + (p.y || 0) * fh
    const w = Math.max(1, (p.w || 0) * fw)
    const h = Math.max(1, (p.h || 0) * fh)
    const rect = doc.createElementNS(SVG_NS, 'rect')
    rect.setAttribute('x', x.toFixed(1))
    rect.setAttribute('y', y.toFixed(1))
    rect.setAttribute('width', w.toFixed(1))
    rect.setAttribute('height', h.toFixed(1))
    rect.setAttribute('rx', '1')
    rect.setAttribute('fill', 'white')
    rect.setAttribute('stroke', '#2a2a2a')
    rect.setAttribute('stroke-width', '0.8')
    if (p.rotation) {
      const cx = x + w / 2, cy = y + h / 2
      rect.setAttribute('transform', `rotate(${p.rotation} ${cx.toFixed(1)} ${cy.toFixed(1)})`)
    }
    group.appendChild(rect)
  }
  floor.insertAdjacentElement('afterend', group)
}

// 整份 svg_markup 字串版：byRoom = { [roomId]: placements }，沒列到的房間保留原樣
export function withRoomFurniture(svgMarkup, byRoom) {
  if (!svgMarkup || !Object.keys(byRoom).length) return svgMarkup
  const doc = new DOMParser().parseFromString(svgMarkup, 'image/svg+xml')
  doc.querySelectorAll('.room-rect').forEach((g) => {
    const placements = byRoom[g.getAttribute('data-room-id')]
    if (placements) drawRoomFurniture(g, placements)
  })
  return new XMLSerializer().serializeToString(doc.documentElement)
}
