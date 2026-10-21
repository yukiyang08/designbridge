<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
import { furnitureLabel } from '@/config/furniture'
import { API_BASE } from '@/config/api'

const _gltfLoader = new GLTFLoader()
// IKEA 官方商品模型是 Draco 壓縮的；解碼器從 three 複製到 public/draco/
_gltfLoader.setDRACOLoader(new DRACOLoader().setDecoderPath('/draco/'))

const FURNITURE_MODEL_URL = {
  sofa: '/models/Sofa_01/Sofa_01_1k.gltf',
  loveseat: '/models/Sofa_01/Sofa_01_1k.gltf',
  armchair: '/models/ArmChair_01/ArmChair_01_1k.gltf',
  chair: '/models/ArmChair_01/ArmChair_01_1k.gltf',
  coffee_table: '/models/CoffeeTable_01/CoffeeTable_01_1k.gltf',
  dining_table: '/models/CoffeeTable_01/CoffeeTable_01_1k.gltf',
  desk: '/models/CoffeeTable_01/CoffeeTable_01_1k.gltf',
  side_table: '/models/CoffeeTable_01/CoffeeTable_01_1k.gltf',
  nightstand: '/models/CoffeeTable_01/CoffeeTable_01_1k.gltf',
  bed: '/models/old_bed_frame/old_bed_frame_1k.gltf',
  bunk_bed: '/models/old_bed_frame/old_bed_frame_1k.gltf',
  wardrobe: '/models/Shelf_01/Shelf_01_1k.gltf',
  bookshelf: '/models/Shelf_01/Shelf_01_1k.gltf',
  shelf: '/models/Shelf_01/Shelf_01_1k.gltf',
  cabinet: '/models/Shelf_01/Shelf_01_1k.gltf',
  dresser: '/models/Shelf_01/Shelf_01_1k.gltf',
  plant: '/models/potted_plant_01/potted_plant_01_1k.gltf',
}
// 同一個模型 URL 只下載/解析一次，跨家具重複使用（clone 場景圖，不是重新 load）
const _gltfCache = new Map()   // url -> Promise<GLTF>
function loadGltfCached(url) {
  if (!_gltfCache.has(url)) {
    _gltfCache.set(url, new Promise((resolve, reject) => {
      _gltfLoader.load(url, resolve, undefined, reject)
    }))
  }
  return _gltfCache.get(url)
}

// props 對應後端 /api/generate 回傳的 scene_graph + layout_render_config——
// 跟 scene_graph_to_depth.py 產生 ControlNet 深度圖用的是同一份家具高度/顏色/相機參數，
// 這裡只是換一種方式（互動 3D）把同樣的資料視覺化給使用者看，不影響生圖流程本身。
const props = defineProps({
  sceneGraph: { type: Object, default: null },   // { furniture_placements: [...] }
  renderConfig: { type: Object, default: null },  // { furniture_heights, furniture_colors, camera }
  spaceInfo: { type: Object, default: null },     // { estimated_size: { width, depth } }（選填）
  geometry: { type: Object, default: null },      // { wallT, openings }（CAD 路徑才有，見 utils/roomGeometry）
  editable: { type: Boolean, default: false },    // true 時可拖曳家具調整位置
  highlightId: { type: String, default: '' },     // 外部指定要標示的家具 id（顯示它的標籤）
  // 家具 id → 正面朝向（up/down/left/right，後端 facing.py 推算，跟平面圖箭頭、生圖一致）。
  // 沒給時沿用 item.rotation（舊行為）
  facing: { type: Object, default: null },
})

// 拖曳結束後回傳更新過的 furniture_placements（跟 sceneGraph.furniture_placements 同格式）
const emit = defineEmits(['layout-changed', 'hover-item'])

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
let lastHoverId = ''
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

// 材質質感依家具類別調整（粗糙度/金屬度），同樣的箱型幾何在光線下才不會全部長得
// 像同一種塑膠——布沙發偏粗糙無反光，桌面/收納偏木質微光澤，燈具立柱偏金屬。
const FURNITURE_MATERIAL = {
  seating: { roughness: 0.85, metalness: 0.0 },
  table:   { roughness: 0.45, metalness: 0.05 },
  bed:     { roughness: 0.8,  metalness: 0.0 },
  lamp:    { roughness: 0.35, metalness: 0.6 },
  plant:   { roughness: 0.7,  metalness: 0.0 },
  storage: { roughness: 0.5,  metalness: 0.05 },
  box:     { roughness: 0.75, metalness: 0.0 },
}

// 後端沒給 furniture_heights（CAD 路徑）時的實際高度（公尺）；不然全部 0.8m 椅子跟衣櫃一樣高
const DEFAULT_HEIGHT = {
  sofa: 0.85, loveseat: 0.85, armchair: 0.85, chair: 0.9,
  coffee_table: 0.42, dining_table: 0.75, desk: 0.75, side_table: 0.5, nightstand: 0.5,
  bed: 0.9, bunk_bed: 1.7, wardrobe: 2.0, bookshelf: 1.8, shelf: 1.2, cabinet: 0.9, dresser: 0.85,
  lamp: 1.5, plant: 1.0,
}
// 白模色：以米白為主，只有木質（桌/櫃）跟植物帶很淡的色，不追求跟之後的渲染同色
const CLAY_COLOR = {
  seating: 0xe8e4dd, table: 0xdcc8aa, bed: 0xf0ece5, lamp: 0xdad6cd,
  plant: 0xb7cbb0, storage: 0xd9c6a8, box: 0xe2ded6,
}

function buildFurnitureMesh(type, w, height, d, colorHex) {
  const category = FURNITURE_CATEGORY[type] || 'box'
  const material = new THREE.MeshStandardMaterial({ color: colorHex, ...FURNITURE_MATERIAL[category] })
  const group = new THREE.Group()

  //  GLTF 真模型暫時停用，先都用程序化箱型；要恢復就把下面這段取消註解
  // const modelUrl = FURNITURE_MODEL_URL[type]
  // if (modelUrl) {
  //   loadGltfCached(modelUrl).then((gltf) => {
  //     const model = gltf.scene.clone(true)   // clone：同一個模型會被多件家具共用
  //     const size = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3())
  //     // 非等比例縮放去對齊佈局要求的 w/height/d——尺寸差太多時會拉伸變形，
  //     // 這就是「模型尺寸沒法對齊任意坪數」那個限制的實際樣子
  //     model.scale.set(w / size.x, height / size.y, d / size.z)
  //     const box = new THREE.Box3().setFromObject(model)
  //     const center = box.getCenter(new THREE.Vector3())
  //     model.position.set(-center.x, -box.min.y, -center.z)
  //     model.traverse((child) => {
  //       if (child.isMesh) { child.castShadow = true; child.receiveShadow = true; child.userData.dragRoot = group }
  //     })
  //     group.add(model)
  //   }).catch((err) => console.warn(`[LayoutPreview3D] ${type} 模型載入失敗:`, err))
  //   return group
  // }

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

  // 拖曳時 raycast 打到的是子網格，統一標記回這個 group，方便找到對應的 furniture item；
  // 順便開陰影，家具彼此才會有接觸陰影，不會像浮在地板上的色塊
  group.traverse((child) => {
    child.userData.dragRoot = group
    if (child.isMesh) { child.castShadow = true; child.receiveShadow = true }
  })
  return group
}

// 有綁 IKEA SKU 的家具載商品 GLB（已是真實尺寸、底面中心為原點、正面朝 +Z），
// 朝向規則與後端 product_meshes.placement_yaw 相同：背靠最近的牆
const HAS_BACK = new Set([
  'sofa', 'loveseat', 'armchair', 'chair', 'bed', 'bunk_bed',
  'wardrobe', 'bookshelf', 'shelf', 'cabinet', 'dresser', 'tv_unit',
])

function productYaw(item, roomWidth, roomDepth) {
  if (HAS_BACK.has(item.type)) {
    const dists = {
      far: item.y, near: 1 - (item.y + item.h), left: item.x, right: 1 - (item.x + item.w),
    }
    const back = Object.keys(dists).reduce((a, b) => (dists[b] < dists[a] ? b : a))
    // 場景 X 是鏡像的（見 buildScene 的 worldX）：平面圖左牆在 +X，背靠左牆要面向 -X
    return { far: Math.PI, near: 0, left: -Math.PI / 2, right: Math.PI / 2 }[back]
  }
  // 桌、燈：模型 X 是長邊，footprint 長邊在深度方向就轉 90°
  return item.w * roomWidth < item.h * roomDepth ? Math.PI / 2 : 0
}

// 正面朝向 → 繞 Y 的角度。場景 X 是鏡像的（平面圖左牆在 +X），所以朝左是 +X。
// 程序化外形的正面在 -Z、商品 GLB 的正面在 +Z，兩者差半圈。
const PROCEDURAL_YAW = { down: 0, up: Math.PI, left: -Math.PI / 2, right: Math.PI / 2 }
const PRODUCT_YAW = { down: Math.PI, up: 0, left: Math.PI / 2, right: -Math.PI / 2 }

function buildProductMesh(item, roomWidth, roomDepth, fallback, front) {
  const group = new THREE.Group()
  loadGltfCached(`${API_BASE}/product-meshes/${item.product_id}.glb`).then((gltf) => {
    const model = gltf.scene.clone(true)
    model.rotation.y = front ? PRODUCT_YAW[front] : productYaw(item, roomWidth, roomDepth)
    model.traverse((child) => {
      child.userData.dragRoot = group
      if (child.isMesh) { child.castShadow = true; child.receiveShadow = true }
    })
    group.add(model)
  }).catch((err) => {
    console.warn(`[LayoutPreview3D] 商品模型 ${item.product_id} 載入失敗，改用程序化外形:`, err)
    const box = fallback()
    box.traverse((child) => { child.userData.dragRoot = group })
    group.add(box)
  })
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
  sprite.scale.set(0.5, 0.125, 1)
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
  // PMREM 環境貼圖是獨立的 GPU 資源，rebuild 時（拖曳家具就會觸發）不會跟著
  // renderer.dispose() 一起被清掉，這裡不主動 dispose 每次重建就會多留一張
  scene?.environment?.dispose()
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
  const camCfg = props.renderConfig?.camera || {}
  const roomWidth = props.spaceInfo?.estimated_size?.width || 5.0
  const roomDepth = props.spaceInfo?.estimated_size?.depth || 4.0
  roomWidthRef = roomWidth
  roomDepthRef = roomDepth
  const wallHeight = 2.6

  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xf1f0ee)

  // 地板
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(roomWidth, roomDepth),
    new THREE.MeshStandardMaterial({ color: 0xe6e4e0, side: THREE.DoubleSide, roughness: 0.85 }),
  )
  floor.rotation.x = -Math.PI / 2
  floor.position.set(0, 0, roomDepth / 2)
  floor.receiveShadow = true
  scene.add(floor)

  // 牆：有 geometry 時依牆厚、門窗開洞；牆都蓋在房間外側，不吃掉家具可用面積。
  // 近相機那面（bottom）不畫，不然擋住視線
  const geo = props.geometry || { wallT: { top: 0.1, left: 0.1, right: 0.1, bottom: 0.1 }, openings: [] }
  const wallMat = new THREE.MeshStandardMaterial({ color: 0xf5f4f2, roughness: 0.95 })
  const glassMat = new THREE.MeshStandardMaterial({ color: 0xbfd8e8, transparent: true, opacity: 0.35 })
  const DOOR_H = 2.0, SILL = 0.9, WIN_TOP = 2.1
  for (const side of ['top', 'left', 'right']) {
    const t = geo.wallT?.[side] ?? 0.1
    const horiz = side === 'top'
    const L = horiz ? roomWidth : roomDepth
    // 沿牆方向 [a,b]（公尺，從 top 牆左端 / 左右牆的遠牆端起算）、高度 [y0,y1] 的一塊牆
    const addBox = (a, b, y0, y1, mat = wallMat) => {
      if (b - a < 1e-4 || y1 - y0 < 1e-4) return
      const m = new THREE.Mesh(new THREE.BoxGeometry(horiz ? b - a : t, y1 - y0, horiz ? t : b - a), mat)
      const mid = (a + b) / 2
      // 跟下面家具的 worldX 用同一套鏡像（見那裡的註解），牆跟門窗洞才會對得上
      // 鏡像後的左右，不會牆在左家具卻跑到右邊。
      if (horiz) m.position.set(roomWidth / 2 - mid, (y0 + y1) / 2, roomDepth + t / 2)
      else m.position.set((side === 'left' ? 1 : -1) * (roomWidth / 2 + t / 2), (y0 + y1) / 2, roomDepth - mid)
      m.castShadow = true
      m.receiveShadow = true
      scene.add(m)
    }
    const ops = (geo.openings || []).filter((o) => o.side === side)
      .map((o) => ({ ...o, a: Math.max(0, o.frac * L - o.width / 2), b: Math.min(L, o.frac * L + o.width / 2) }))
      .sort((p, q) => p.a - q.a)
    let cur = 0
    for (const o of ops) {
      addBox(cur, o.a, 0, wallHeight)
      if (o.type === 'door') addBox(o.a, o.b, DOOR_H, wallHeight)
      else {
        addBox(o.a, o.b, 0, SILL)
        addBox(o.a, o.b, WIN_TOP, wallHeight)
        addBox(o.a, o.b, SILL, WIN_TOP, glassMat)
      }
      cur = Math.max(cur, o.b)
    }
    addBox(cur, L, 0, wallHeight)
  }

  // Hemisphere（暖色天光/冷色地面反光）取代純白 ambient，物件在不同角度才有自然的
  // 色溫差異，不是整個場景被同一種死白光打平
  scene.add(new THREE.HemisphereLight(0xfff3e0, 0x6b5a45, 0.85))
  const dirLight = new THREE.DirectionalLight(0xfff8ef, 0.9)
  dirLight.position.set(2, 4, -2)
  dirLight.castShadow = true
  dirLight.shadow.mapSize.set(1024, 1024)
  const shadowSpan = Math.max(roomWidth, roomDepth)
  dirLight.shadow.camera.left = -shadowSpan
  dirLight.shadow.camera.right = shadowSpan
  dirLight.shadow.camera.top = shadowSpan
  dirLight.shadow.camera.bottom = -shadowSpan
  dirLight.shadow.camera.near = 0.5
  dirLight.shadow.camera.far = 20
  dirLight.shadow.bias = -0.001
  scene.add(dirLight)

  // 家具：座標慣例跟 scene_graph_to_depth.py 一致——
  // floor-plan x∈[0,1] 左→右，y∈[0,1] 遠牆→近相機側；(x,y) 是左上角。
  furnitureMeshes.length = 0
  for (const item of items) {
    const height = heights[item.type] ?? DEFAULT_HEIGHT[item.type] ?? heights.default ?? 0.8
    const colorHex = CLAY_COLOR[FURNITURE_CATEGORY[item.type] || 'box']
    const w = Math.max(item.w || 0.1, 0.02) * roomWidth
    const d = Math.max(item.h || 0.1, 0.02) * roomDepth
    const front = props.facing?.[item.id]
    // 朝左右時家具的「寬」沿著平面圖的深度方向：先照正面朝前的尺寸建，再轉過去
    const sideways = front === 'left' || front === 'right'
    const procedural = () => {
      const g = buildFurnitureMesh(item.type, sideways ? d : w, height, sideways ? w : d, colorHex)
      if (front) g.rotation.y = PROCEDURAL_YAW[front]
      return g
    }
    const furnitureGroup = item.product_id
      ? buildProductMesh(item, roomWidth, roomDepth, procedural, front)
      : procedural()

    const cx = (item.x || 0) + (item.w || 0) / 2
    const cy = (item.y || 0) + (item.h || 0) / 2
    // 相機站在近牆看向房間深處（eye.z 比 target.z 更負），OrbitControls 算出來的
    // 螢幕右 = world -X，不是直覺的 +X——不翻轉的話，平面圖左邊的家具會跑到
    // 3D 畫面右邊。這裡直接把 X 鏡像回來，讓左右對應視覺上的左右，不去動相機
    // 本身（距離/俯仰角跟生圖的投影相機要對齊，不能改）。
    const worldX = (0.5 - cx) * roomWidth
    const worldZ = (1 - cy) * roomDepth
    furnitureGroup.position.set(worldX, 0, worldZ)
    // X 鏡像會讓旋轉方向也跟著反過來，角度正負號要一起翻才會跟平面圖一致。
    // 商品模型的朝向已由 productYaw 決定，跟後端深度投影一致，不吃 item.rotation
    if (!item.product_id && !front) furnitureGroup.rotation.y = THREE.MathUtils.degToRad(item.rotation || 0)

    const label = makeLabel(furnitureLabel(item.type))
    label.position.set(0, height + 0.15, 0)
    label.visible = false   // hover 才顯示，平常標籤會蓋住家具
    label.userData.dragRoot = furnitureGroup   // 加在 buildFurnitureMesh 的 traverse 之後才 add，要補標記
    furnitureGroup.add(label)

    scene.add(furnitureGroup)
    furnitureMeshes.push({ mesh: furnitureGroup, item: { ...item }, label })
  }

  // 相機：fov_v_deg 本身就是 PerspectiveCamera 吃的垂直視角，不用再換算
  const width = container.clientWidth || 640
  const height2 = container.clientHeight || 480
  const aspect = width / height2
  let vfovDeg = camCfg.fov_v_deg || 58
  let eyeHeight = camCfg.eye_height || 2.2
  let setback = camCfg.setback ?? 2.6
  const targetH = camCfg.target_h ?? 0.5
  const targetDepthFrac = camCfg.target_depth_frac ?? 0.58
  let eyeXFrac = camCfg.eye_x_frac ?? 0.5
  let targetXFrac = camCfg.target_x_frac ?? 0.5
  // 小房間最低觀看距離：跟後端 camera_projection.fit_camera_to_room 同一條規則，預覽才對得上生成
  if (camCfg.min_view_dist) {
    const tz = targetDepthFrac * roomDepth
    const dist = Math.hypot((targetXFrac - eyeXFrac) * roomWidth, tz + setback)
    // 房內退得開就只調後退距離；得退到近牆外才整套調整
    const inside = Math.sqrt(Math.max(camCfg.min_view_dist ** 2 - ((targetXFrac - eyeXFrac) * roomWidth) ** 2, 0)) - tz
    if (dist < camCfg.min_view_dist && inside <= 0) {
      setback = inside
    } else if (dist < camCfg.min_view_dist) {
      const rad = Math.PI / 180
      eyeXFrac = 0.5 + (eyeXFrac - 0.5) * 0.5
      targetXFrac = 0.5 + (targetXFrac - 0.5) * 0.5
      const dx = (targetXFrac - eyeXFrac) * roomWidth
      vfovDeg = 2 * Math.atan(Math.tan(vfovDeg * rad / 2) * dist / camCfg.min_view_dist) / rad
      setback = Math.sqrt(Math.max(camCfg.min_view_dist ** 2 - dx * dx, 0)) - tz
      // 畫面左右要落在近牆開口內，否則會看到側牆外的空白（同後端 _fov_inside_opening）
      if (setback > 0) {
        const ex = eyeXFrac * roomWidth, tx = targetXFrac * roomWidth
        const view = Math.atan2(tx - ex, tz + setback)
        const half = Math.min(...[0, roomWidth].map(cx => Math.abs(view - Math.atan2(cx - ex, setback)))) * 0.9
        vfovDeg = Math.min(vfovDeg, 2 * Math.atan(Math.tan(half) / aspect) / rad)
      }
      eyeHeight = Math.max(eyeHeight, camCfg.small_room_eye_h || eyeHeight)
    }
  }
  // 斜角視角的左右位置；跟家具 worldX 用同一套鏡像換算
  const eyeX = (0.5 - eyeXFrac) * roomWidth
  const targetX = (0.5 - targetXFrac) * roomWidth
  camera = new THREE.PerspectiveCamera(vfovDeg, aspect, 0.05, 50)
  camera.position.set(eyeX, eyeHeight, -setback)

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height2)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  // ACES 色調映射 + sRGB 輸出：預設的線性輸出偏灰偏平，這兩行是最低成本換到「像張照片」
  // 對比與飽和度的做法，不用調任何家具顏色本身
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.1
  renderer.outputColorSpace = THREE.SRGBColorSpace
  container.innerHTML = ''
  container.appendChild(renderer.domElement)
  renderer.domElement.style.touchAction = 'none'
  if (props.editable) renderer.domElement.style.cursor = 'grab'

  // PMREM 環境反射（three 內建的 RoomEnvironment，不用外部 HDR 檔）：家具材質的
  // roughness/metalness 才有東西可以反射，不然低粗糙度的表面在純方向光下看起來很乾
  const pmrem = new THREE.PMREMGenerator(renderer)
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
  pmrem.dispose()

  // 初始朝向對齊 camera_projection.py 的 look-at 相機（同一個瞄準點），這樣使用者看到的
  // 就是生圖實際會用的取景角度（候選角度評分後實際選中的那組，不一定等於這裡的 base
  // 參數——這個 3D 預覽固定用 base，只是給使用者一個大致對齊的初始視角，之後仍可自由拖曳旋轉）。
  controls = new OrbitControls(camera, renderer.domElement)
  controls.target.set(targetX, targetH, targetDepthFrac * roomDepth)
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
  applyHighlight()
}

function applyHighlight() {
  for (const f of furnitureMeshes) f.label.visible = !!props.highlightId && f.item.id === props.highlightId
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
  setPointerNDC(event)
  raycaster.setFromCamera(pointerNDC, camera)
  if (!draggedEntry) {
    const hit = raycaster.intersectObjects(furnitureMeshes.map((f) => f.mesh), true)[0]
    const root = hit?.object.userData.dragRoot
    for (const f of furnitureMeshes) f.label.visible = f.mesh === root
    const hoverId = furnitureMeshes.find((f) => f.mesh === root)?.item.id ?? ''
    if (hoverId !== lastHoverId) { lastHoverId = hoverId; emit('hover-item', hoverId) }
    return
  }
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
  // 世界座標換回正規化 floor-plan 座標（buildScene 那段鏡像轉換的反運算）
  const cx = 0.5 - mesh.position.x / roomWidthRef
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

watch(() => props.highlightId, applyHighlight)

watch(() => props.sceneGraph, () => {
  disposeScene()
  buildScene()
})

// 健檢每次都回新物件；值沒變就不重建，不然轉好的視角會被重設
watch(() => JSON.stringify(props.facing || {}), () => {
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
  background: #f1f0ee;
  border: 1px solid #dcdad6;
}
.layout-3d-hint {
  font-size: 0.72rem;
  color: var(--db-secondary);
  text-align: center;
  margin: 0;
}
</style>
