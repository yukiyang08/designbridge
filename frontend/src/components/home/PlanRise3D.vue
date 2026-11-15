<script setup>

import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as THREE from 'three'
import { seg } from '@/composables/useScrollProgress'

const props = defineProps({
  svg: { type: String, required: true },
  t: { type: Number, default: 0 },
})
const emit = defineEmits(['ready'])

const WALL_H = 64
const FOV = 30
// 俯衝終點：客廳右下角、人眼高度，看向沙發與電視牆（SVG 座標，y 為高度）
const DIVE = { eye: [404, 34, 346], look: [215, 16, 170] }
const PALETTE = ['#b9ad9f', '#a39b94', '#c9c4bb', '#8f867d']   // 品牌灰褐系

const host = ref(null)
let renderer, scene, camera, walls, glass, shadowLight, ro
let VW = 765, VH = 650
const eye = new THREE.Vector3(), look = new THREE.Vector3(), up = new THREE.Vector3()
const sv = (v, [x, y, z]) => v.set(x - VW / 2, y, z - VH / 2)
const furniture = []

const ease = (x) => x * x * (3 - 2 * x)
const backOut = (x) => 1 + 2.2 * (x - 1) ** 3 + 1.2 * (x - 1) ** 2

const R = (el) => {
  const n = (k) => parseFloat(el.getAttribute(k))
  return { x: n('x'), y: n('y'), w: n('width'), h: n('height'), fill: el.getAttribute('fill') || '' }
}
const inside = (r, x, y) => x > r.x && x < r.x + r.w && y > r.y && y < r.y + r.h
const contains = (a, b) => b.x >= a.x - 0.5 && b.y >= a.y - 0.5 && b.x + b.w <= a.x + a.w + 0.5 && b.y + b.h <= a.y + a.h + 0.5

function build(doc) {
  const svg = doc.documentElement
  const vb = svg.getAttribute('viewBox').split(/\s+/).map(Number)
  VW = vb[2]; VH = vb[3]
  const c = [...svg.children]
  // 結構同 StoryPlan：2 外牆、10–40 門窗
  const outer = R(c[2])
  const floors = [...svg.querySelectorAll('.room-floor')].map(R)
  const openings = c.slice(10, 41).filter((e) => e.tagName === 'rect').map(R)
  const windows = openings.filter((r) => r.fill === '#c0daf8')
  const holes = [...floors, ...openings.filter((r) => r.fill !== '#c0daf8')]

  const unit = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0)   // 底面貼地，scale.y 就是長高
  const pos = (r) => [r.x + r.w / 2 - VW / 2, r.y + r.h / 2 - VH / 2]

  // 牆：座標壓縮成格子，不屬於房間地板或門洞的格子就是牆；窗的位置只留窗台
  const cut = (k, len) => [...new Set([outer[k], outer[k] + outer[len],
    ...[...holes, ...windows].flatMap((r) => [r[k], r[k] + r[len]])]
    .map((v) => Math.min(outer[k] + outer[len], Math.max(outer[k], v))))].sort((a, b) => a - b)
  const xs = cut('x', 'w'), ys = cut('y', 'h')
  const cells = []
  for (let i = 0; i < xs.length - 1; i++) for (let j = 0; j < ys.length - 1; j++) {
    const cx = (xs[i] + xs[i + 1]) / 2, cy = (ys[j] + ys[j + 1]) / 2
    if (holes.some((r) => inside(r, cx, cy))) continue
    const sill = windows.some((r) => inside(r, cx, cy))
    cells.push({ x: xs[i], y: ys[j], w: xs[i + 1] - xs[i], h: ys[j + 1] - ys[j], hgt: sill ? WALL_H * 0.35 : WALL_H })
  }
  walls = new THREE.InstancedMesh(unit, new THREE.MeshStandardMaterial({ color: '#efebe5', roughness: 0.95 }), cells.length)
  const m = new THREE.Object3D()
  cells.forEach((r, i) => {
    const [x, z] = pos(r)
    m.position.set(x, 0, z); m.scale.set(r.w, r.hgt, r.h); m.updateMatrix()
    walls.setMatrixAt(i, m.matrix)
  })
  walls.castShadow = walls.receiveShadow = true
  scene.add(walls)

  glass = new THREE.Group()
  const glassMat = new THREE.MeshStandardMaterial({ color: '#c0daf8', transparent: true, opacity: 0.45, roughness: 0.2 })
  for (const r of windows) {
    const g = new THREE.Mesh(unit, glassMat)
    const [x, z] = pos(r)
    g.position.set(x, WALL_H * 0.35, z)
    g.scale.set(Math.max(2, r.w * (r.w > r.h ? 1 : 0.3)), WALL_H * 0.5, Math.max(2, r.h * (r.h > r.w ? 1 : 0.3)))
    glass.add(g)
  }
  scene.add(glass)

  // 家具：有填色的矩形各長成一個方塊；被包在別的矩形裡的（椅背、扶手、枕頭）長得比本體高一點
  let n = 0
  for (const g of svg.querySelectorAll('.room-furniture')) {
    const kept = []
    for (const el of g.querySelectorAll('rect')) {
      const r = R(el)
      if (!r.fill || r.fill === 'none') continue
      const parent = kept.find((k) => contains(k, r))
      const tall = r.fill.startsWith('url')   // 斜線填色＝衣櫃
      const base = tall ? WALL_H * 0.75 : Math.min(14, Math.max(4, Math.min(r.w, r.h) * 0.4))
      const hgt = parent ? parent.hgt * 1.55 : base
      if (!parent) { r.hgt = hgt; r.idx = n++; kept.push(r) }
      const mesh = new THREE.Mesh(unit, new THREE.MeshStandardMaterial({
        color: PALETTE[(parent ?? r).idx % PALETTE.length], roughness: 0.85,
      }))
      const [x, z] = pos(r)
      mesh.position.set(x, 0, z)
      mesh.scale.set(r.w, 0.001, r.h)
      mesh.castShadow = mesh.receiveShadow = true
      mesh.userData = { hgt, order: (parent ?? r).idx }
      furniture.push(mesh)
      scene.add(mesh)
    }
  }
  furniture.total = Math.max(1, n)
}

function draw() {
  if (!renderer) return
  const t = props.t
  // 相機：正俯視（與 SVG 重合）→ 斜角，之後持續慢慢環繞
  const k = ease(seg(t, 0.02, 0.5))
  const phi = THREE.MathUtils.degToRad(54) * k
  const theta = THREE.MathUtils.degToRad(-18 * k - 16 * t)
  const dist = (VH / 2 / Math.tan(THREE.MathUtils.degToRad(FOV / 2))) * (1 - 0.04 * k)
  camera.position.set(dist * Math.sin(phi) * Math.sin(theta), dist * Math.cos(phi), dist * Math.sin(phi) * Math.cos(theta))
  up.set(-Math.sin(theta), 0, -Math.cos(theta))   // 正俯視時 lookAt 仍有確定的「上」
  // 俯衝：位置、視線、視角一起插值到客廳內
  const d = ease(seg(t, 0.76, 1))
  camera.position.lerp(sv(eye, DIVE.eye), d)
  camera.up.copy(up.lerp(eye.set(0, 1, 0), d).normalize())
  camera.lookAt(look.set(0, 0, 0).lerp(sv(eye, DIVE.look), d))
  camera.fov = FOV + (62 - FOV) * d
  camera.updateProjectionMatrix()

  const w = ease(seg(t, 0.1, 0.42))
  walls.visible = glass.visible = w > 0
  walls.scale.y = glass.scale.y = Math.max(w, 0.001)
  for (const f of furniture) {
    const a = 0.34 + 0.24 * (f.userData.order / furniture.total)
    const g = seg(t, a, a + 0.14)
    f.visible = g > 0
    f.scale.y = Math.max(0.001, f.userData.hgt * backOut(g))
  }
  renderer.render(scene, camera)
}

function resize() {
  const el = host.value
  if (!el || !renderer) return
  renderer.setSize(el.clientWidth, el.clientHeight, false)
  camera.aspect = el.clientWidth / Math.max(1, el.clientHeight)
  camera.updateProjectionMatrix()
  draw()
}

onMounted(() => {
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true })
  } catch { return }   // 沒有 WebGL：父層保留原本的 2D 演出
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  renderer.setClearColor('#ffffff')
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  host.value.appendChild(renderer.domElement)

  scene = new THREE.Scene()
  camera = new THREE.PerspectiveCamera(FOV, 1.6, 4, 5000)
  scene.add(new THREE.HemisphereLight('#ffffff', '#d8d2c8', 1.9))
  shadowLight = new THREE.DirectionalLight('#fff4e4', 1.6)
  shadowLight.position.set(-260, 420, 180)
  shadowLight.castShadow = true
  shadowLight.shadow.mapSize.set(2048, 2048)
  Object.assign(shadowLight.shadow.camera, { left: -420, right: 420, top: 420, bottom: -420, near: 10, far: 1200 })
  shadowLight.shadow.bias = -0.0005
  scene.add(shadowLight)

  build(new DOMParser().parseFromString(props.svg, 'image/svg+xml'))

  // 地面：SVG 畫到 canvas 當貼圖（不受光，顏色與 2D 完全一致），上面再疊一層只收陰影的透明面
  const img = new Image()
  const url = URL.createObjectURL(new Blob([props.svg], { type: 'image/svg+xml' }))
  img.onload = () => {
    URL.revokeObjectURL(url)
    const cv = document.createElement('canvas')
    cv.width = VW * 2; cv.height = VH * 2
    cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height)
    const tex = new THREE.CanvasTexture(cv)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy()
    const plane = new THREE.PlaneGeometry(VW, VH).rotateX(-Math.PI / 2)
    scene.add(new THREE.Mesh(plane, new THREE.MeshBasicMaterial({ map: tex })))
    const shadow = new THREE.Mesh(plane, new THREE.ShadowMaterial({ opacity: 0.22 }))
    shadow.position.y = 0.05
    shadow.receiveShadow = true
    scene.add(shadow)
    resize()
    emit('ready')
  }
  img.src = url

  ro = new ResizeObserver(resize)
  ro.observe(host.value)
})
watch(() => props.t, draw)

onBeforeUnmount(() => {
  ro?.disconnect()
  scene?.traverse((o) => { o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose() })
  renderer?.dispose()
})
</script>

<template>
  <div ref="host" class="rise"></div>
</template>

<style scoped>
.rise :deep(canvas) { display: block; width: 100%; height: 100%; }
</style>
