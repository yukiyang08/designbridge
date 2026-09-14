<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { furnitureLabel } from '@/config/furniture'

// props 對應後端 /api/generate 回傳的 scene_graph + layout_render_config——
// 跟 scene_graph_to_depth.py 產生 ControlNet 深度圖用的是同一份家具高度/顏色/相機參數，
// 這裡只是換一種方式（互動 3D）把同樣的資料視覺化給使用者看，不影響生圖流程本身。
const props = defineProps({
  sceneGraph: { type: Object, default: null },   // { furniture_placements: [...] }
  renderConfig: { type: Object, default: null },  // { furniture_heights, furniture_colors, camera }
  spaceInfo: { type: Object, default: null },     // { estimated_size: { width, depth } }（選填）
  editable: { type: Boolean, default: false },    // true 時可拖曳家具調整位置
})

// 拖曳結束後回傳更新過的 furniture_placements（跟 sceneGraph.furniture_placements 同格式）
const emit = defineEmits(['layout-changed'])

const canvasWrap = ref(null)
let renderer = null
let scene = null
let camera = null
let controls = null
let animId = null
let resizeObserver = null

// 拖曳用：房間尺寸（buildScene 時定住，換算世界座標 ↔ 正規化座標要用同一份）
let roomWidthRef = 5.0
let roomDepthRef = 4.0
const furnitureMeshes = []   // [{ mesh, item }]，item 是原始 furniture_placements 物件

const raycaster = new THREE.Raycaster()
const pointerNDC = new THREE.Vector2()
const dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
let draggedEntry = null
let dragOffset = new THREE.Vector3()

// 家具長什麼樣：不用外部模型（授權/下載/比對尺寸都是額外工作量），純用幾何形狀組
// 出看得出來是什麼的輪廓——沙發/椅子有椅背扶手、桌子有桌腳、床有床頭板、燈跟植物
// 是柱體+球/錐體。沒對到分類的（櫃類、螢幕、地毯…）維持原本的長方體，那些形狀本來
// 就是箱型，不需要特別處理。group 原點固定在「地板、水平中心」，跟呼叫端的
// position.set(worldX, 0, worldZ) 慣例對齊。
const FURNITURE_CATEGORY = {
  sofa: 'seating', loveseat: 'seating', armchair: 'seating', chair: 'seating',
  coffee_table: 'table', dining_table: 'table', desk: 'table',
  side_table: 'table', nightstand: 'table',
  bed: 'bed', bunk_bed: 'bed',
  lamp: 'lamp',
  plant: 'plant',
  wardrobe: 'storage', bookshelf: 'storage', shelf: 'storage',
  cabinet: 'storage', dresser: 'storage',
}

function buildFurnitureMesh(type, w, height, d, colorHex) {
  const material = new THREE.MeshStandardMaterial({ color: colorHex })
  const group = new THREE.Group()
  const category = FURNITURE_CATEGORY[type] || 'box'

  if (category === 'seating') {
    const seatH = height * 0.45
    const seat = new THREE.Mesh(new THREE.BoxGeometry(w, seatH, d * 0.85), material)
    seat.position.set(0, seatH / 2, -d * 0.075)
    group.add(seat)

    const backH = height - seatH
    const back = new THREE.Mesh(new THREE.BoxGeometry(w, backH, d * 0.18), material)
    back.position.set(0, seatH + backH / 2, d / 2 - d * 0.09)
    group.add(back)

    if (type === 'sofa' || type === 'loveseat' || type === 'armchair') {
      const armW = Math.min(w * 0.12, 0.15)
      const armH = height * 0.65
      for (const sign of [-1, 1]) {
        const arm = new THREE.Mesh(new THREE.BoxGeometry(armW, armH, d * 0.85), material)
        arm.position.set(sign * (w / 2 - armW / 2), armH / 2, -d * 0.075)
        group.add(arm)
      }
    }
  } else if (category === 'table') {
    const topH = Math.max(height * 0.08, 0.03)
    const top = new THREE.Mesh(new THREE.BoxGeometry(w, topH, d), material)
    top.position.set(0, height - topH / 2, 0)
    group.add(top)

    const legR = Math.max(Math.min(w, d) * 0.04, 0.015)
    const legH = height - topH
    const legGeo = new THREE.CylinderGeometry(legR, legR, legH, 8)
    for (const sx of [-1, 1]) {
      for (const sz of [-1, 1]) {
        const leg = new THREE.Mesh(legGeo, material)
        leg.position.set(sx * (w / 2 - legR * 1.5), legH / 2, sz * (d / 2 - legR * 1.5))
        group.add(leg)
      }
    }
  } else if (category === 'bed') {
    const mattressH = height * 0.4
    const mattress = new THREE.Mesh(new THREE.BoxGeometry(w, mattressH, d * 0.92), material)
    mattress.position.set(0, mattressH / 2, -d * 0.04)
    group.add(mattress)

    const headboard = new THREE.Mesh(new THREE.BoxGeometry(w, height, d * 0.06), material)
    headboard.position.set(0, height / 2, d / 2 - d * 0.03)
    group.add(headboard)
  } else if (category === 'lamp') {
    const poleR = Math.max(Math.min(w, d) * 0.08, 0.015)
    const poleH = height * 0.85
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(poleR, poleR, poleH, 8), material)
    pole.position.set(0, poleH / 2, 0)
    group.add(pole)

    const shadeH = height - poleH
    const shade = new THREE.Mesh(new THREE.ConeGeometry(Math.max(w, d) * 0.4, shadeH, 12), material)
    shade.position.set(0, poleH + shadeH / 2, 0)
    group.add(shade)
  } else if (category === 'plant') {
    const potH = height * 0.3
    const pot = new THREE.Mesh(
      new THREE.CylinderGeometry(Math.max(w, d) * 0.35, Math.max(w, d) * 0.25, potH, 10),
      material,
    )
    pot.position.set(0, potH / 2, 0)
    group.add(pot)

    const foliage = new THREE.Mesh(new THREE.IcosahedronGeometry(Math.max(w, d) * 0.45, 0), material)
    foliage.position.set(0, potH + (height - potH) * 0.5, 0)
    group.add(foliage)
  } else if (category === 'storage') {
    const body = new THREE.Mesh(new THREE.BoxGeometry(w, height, d), material)
    body.position.set(0, height / 2, 0)
    group.add(body)

    // 門片/層板分隔線：正面貼幾條窄窄的深色長條，一眼看出是櫃子不是素色箱子
    const lineMat = new THREE.MeshStandardMaterial({ color: 0x2a2a2a })
    const shelfCount = Math.max(1, Math.round(height / 0.4))
    for (let i = 1; i < shelfCount; i++) {
      const line = new THREE.Mesh(new THREE.BoxGeometry(w * 0.96, height * 0.015, 0.01), lineMat)
      line.position.set(0, (height / shelfCount) * i, d / 2 + 0.005)
      group.add(line)
    }
    const doorGap = new THREE.Mesh(new THREE.BoxGeometry(height * 0.015, height * 0.9, 0.012), lineMat)
    doorGap.position.set(0, height / 2, d / 2 + 0.006)
    group.add(doorGap)
  } else {
    const box = new THREE.Mesh(new THREE.BoxGeometry(w, height, d), material)
    box.position.set(0, height / 2, 0)
    group.add(box)
  }

  // 拖曳時 raycast 打到的是子網格，統一標記回這個 group，方便找到對應的 furniture item
  group.traverse((child) => { child.userData.dragRoot = group })
  return group
}

function makeLabel(text) {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 64
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = 'rgba(0,0,0,0.65)'
  ctx.fillRect(0, 0, 256, 64)
  ctx.fillStyle = '#fff'
  ctx.font = '28px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(text, 128, 42)
  const texture = new THREE.CanvasTexture(canvas)
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false }))
  sprite.scale.set(0.8, 0.2, 1)
  return sprite
}

function disposeScene() {
  if (animId) cancelAnimationFrame(animId)
  animId = null
  if (renderer) {
    renderer.domElement.removeEventListener('pointerdown', onPointerDown)
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
  }
  controls?.dispose()
  renderer?.dispose()
  if (canvasWrap.value) canvasWrap.value.innerHTML = ''
  renderer = null
  scene = null
  camera = null
  controls = null
  furnitureMeshes.length = 0
  draggedEntry = null
}

function buildScene() {
  const container = canvasWrap.value
  const items = props.sceneGraph?.furniture_placements
  if (!container || !items || !items.length) return

  const heights = props.renderConfig?.furniture_heights || {}
  const colors = props.renderConfig?.furniture_colors || {}
  const camCfg = props.renderConfig?.camera || {}
  const roomWidth = props.spaceInfo?.estimated_size?.width || 5.0
  const roomDepth = props.spaceInfo?.estimated_size?.depth || 4.0
  roomWidthRef = roomWidth
  roomDepthRef = roomDepth
  const wallHeight = 2.6

  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xf3ede3)

  // 地板
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(roomWidth, roomDepth),
    new THREE.MeshStandardMaterial({ color: 0xe0d4c0, side: THREE.DoubleSide }),
  )
  floor.rotation.x = -Math.PI / 2
  floor.position.set(0, 0, roomDepth / 2)
  scene.add(floor)

  // 簡易牆面（純視覺參考，不是精確幾何）
  const wallMat = new THREE.MeshStandardMaterial({
    color: 0xffffff, side: THREE.DoubleSide, transparent: true, opacity: 0.55,
  })
  const backWall = new THREE.Mesh(new THREE.PlaneGeometry(roomWidth, wallHeight), wallMat)
  backWall.position.set(0, wallHeight / 2, roomDepth)
  scene.add(backWall)
  const leftWall = new THREE.Mesh(new THREE.PlaneGeometry(roomDepth, wallHeight), wallMat)
  leftWall.rotation.y = Math.PI / 2
  leftWall.position.set(-roomWidth / 2, wallHeight / 2, roomDepth / 2)
  scene.add(leftWall)
  const rightWall = leftWall.clone()
  rightWall.position.set(roomWidth / 2, wallHeight / 2, roomDepth / 2)
  scene.add(rightWall)

  scene.add(new THREE.AmbientLight(0xffffff, 0.75))
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.55)
  dirLight.position.set(2, 4, -2)
  scene.add(dirLight)

  // 家具：座標慣例跟 scene_graph_to_depth.py 一致——
  // floor-plan x∈[0,1] 左→右，y∈[0,1] 遠牆→近相機側；(x,y) 是左上角。
  furnitureMeshes.length = 0
  for (const item of items) {
    const height = heights[item.type] ?? heights.default ?? 0.8
    const colorHex = colors[item.type] ?? colors.default ?? '#96c896'
    const w = Math.max(item.w || 0.1, 0.02) * roomWidth
    const d = Math.max(item.h || 0.1, 0.02) * roomDepth
    const furnitureGroup = buildFurnitureMesh(item.type, w, height, d, colorHex)

    const cx = (item.x || 0) + (item.w || 0) / 2
    const cy = (item.y || 0) + (item.h || 0) / 2
    const worldX = (cx - 0.5) * roomWidth
    const worldZ = (1 - cy) * roomDepth
    furnitureGroup.position.set(worldX, 0, worldZ)
    furnitureGroup.rotation.y = -THREE.MathUtils.degToRad(item.rotation || 0)

    const label = makeLabel(furnitureLabel(item.type))
    label.position.set(0, height + 0.15, 0)
    label.userData.dragRoot = furnitureGroup   // 加在 buildFurnitureMesh 的 traverse 之後才 add，要補標記
    furnitureGroup.add(label)

    scene.add(furnitureGroup)
    furnitureMeshes.push({ mesh: furnitureGroup, item: { ...item } })
  }

  // 相機：hfov_deg 是水平視角，PerspectiveCamera 吃垂直視角，換算一下
  const width = container.clientWidth || 640
  const height2 = container.clientHeight || 480
  const aspect = width / height2
  const hfovRad = THREE.MathUtils.degToRad(camCfg.hfov_deg || 65)
  const vfovDeg = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(hfovRad / 2) / aspect))
  const eyeHeight = camCfg.eye_height || 1.4
  const setback = camCfg.setback || 0.8
  const pitchRad = THREE.MathUtils.degToRad(camCfg.pitch_deg ?? -16)
  camera = new THREE.PerspectiveCamera(vfovDeg, aspect, 0.05, 50)
  camera.position.set(0, eyeHeight, -setback)

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height2)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  container.innerHTML = ''
  container.appendChild(renderer.domElement)
  renderer.domElement.style.touchAction = 'none'
  if (props.editable) renderer.domElement.style.cursor = 'grab'

  // 初始朝向對齊 scene_graph_to_depth.py 的投影相機（同一個俯角），這樣使用者看到的
  // 就是生圖實際會用的取景角度。沿著相機視線（+Z、下傾 pitchRad）取一個落在房間中段
  // 的注視點；使用者之後仍可自由拖曳旋轉。
  const lookDist = (roomDepth / 2 + setback) / Math.cos(pitchRad)
  controls = new OrbitControls(camera, renderer.domElement)
  controls.target.set(
    0,
    eyeHeight + Math.sin(pitchRad) * lookDist,
    -setback + Math.cos(pitchRad) * lookDist,
  )
  controls.update()

  if (props.editable) {
    renderer.domElement.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
  }

  const animate = () => {
    animId = requestAnimationFrame(animate)
    controls.update()
    renderer.render(scene, camera)
  }
  animate()
}

function setPointerNDC(event) {
  const rect = renderer.domElement.getBoundingClientRect()
  pointerNDC.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
  pointerNDC.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
}

function onPointerDown(event) {
  setPointerNDC(event)
  raycaster.setFromCamera(pointerNDC, camera)
  // 家具現在是多個子網格組成的 group（座椅+椅背+扶手等），recursive raycast 打到的是
  // 子網格，用 userData.dragRoot 找回它所屬的 group
  const hits = raycaster.intersectObjects(furnitureMeshes.map((f) => f.mesh), true)
  if (!hits.length) return
  const rootGroup = hits[0].object.userData.dragRoot
  draggedEntry = furnitureMeshes.find((f) => f.mesh === rootGroup)
  if (!draggedEntry) return

  controls.enabled = false
  const hitPoint = new THREE.Vector3()
  raycaster.ray.intersectPlane(dragPlane, hitPoint)
  dragOffset.copy(draggedEntry.mesh.position).sub(hitPoint)
  renderer.domElement.style.cursor = 'grabbing'
  event.preventDefault()
}

function onPointerMove(event) {
  if (!draggedEntry) return
  setPointerNDC(event)
  raycaster.setFromCamera(pointerNDC, camera)
  const hitPoint = new THREE.Vector3()
  if (!raycaster.ray.intersectPlane(dragPlane, hitPoint)) return

  const { item, mesh } = draggedEntry
  const halfW = (item.w || 0.1) * roomWidthRef / 2
  const halfD = (item.h || 0.1) * roomDepthRef / 2
  const newX = THREE.MathUtils.clamp(hitPoint.x + dragOffset.x, -roomWidthRef / 2 + halfW, roomWidthRef / 2 - halfW)
  const newZ = THREE.MathUtils.clamp(hitPoint.z + dragOffset.z, halfD, roomDepthRef - halfD)
  mesh.position.x = newX
  mesh.position.z = newZ
}

function onPointerUp() {
  if (!draggedEntry) return
  const { item, mesh } = draggedEntry
  // 世界座標換回正規化 floor-plan 座標（buildScene 那段轉換的反運算）
  const cx = mesh.position.x / roomWidthRef + 0.5
  const cy = 1 - mesh.position.z / roomDepthRef
  item.x = Number((cx - (item.w || 0) / 2).toFixed(4))
  item.y = Number((cy - (item.h || 0) / 2).toFixed(4))

  draggedEntry = null
  controls.enabled = true
  renderer.domElement.style.cursor = 'grab'
  emit('layout-changed', furnitureMeshes.map((f) => f.item))
}

function handleResize() {
  if (!renderer || !camera || !canvasWrap.value) return
  const w = canvasWrap.value.clientWidth
  const h = canvasWrap.value.clientHeight
  if (!w || !h) return
  renderer.setSize(w, h)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}

onMounted(() => {
  buildScene()
  resizeObserver = new ResizeObserver(handleResize)
  if (canvasWrap.value) resizeObserver.observe(canvasWrap.value)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  disposeScene()
})

watch(() => props.sceneGraph, () => {
  disposeScene()
  buildScene()
})
</script>

<template>
  <div class="layout-3d-wrap">
    <div ref="canvasWrap" class="layout-3d-canvas"></div>
    <p class="layout-3d-hint">
      {{ editable ? '拖曳家具調整位置・拖曳空白處旋轉視角・滾輪縮放' : '拖曳旋轉・滾輪縮放' }}
      — 位置僅供參考，跟實際生成圖的細節不會完全一致
    </p>
  </div>
</template>

<style scoped>
.layout-3d-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.layout-3d-canvas {
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: 12px;
  overflow: hidden;
  background: #f3ede3;
  border: 1px solid #ddd0c0;
}
.layout-3d-hint {
  font-size: 0.72rem;
  color: var(--text-4, #999);
  text-align: center;
  margin: 0;
}
</style>
