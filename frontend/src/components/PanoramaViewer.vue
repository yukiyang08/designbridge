<script setup>
/**
 * 360° 環景檢視器。
 *
 * · 縮放用 FOV（視野角），不是相機距離——球心視角下相機不能移動，改 distance 沒有任何效果。
 *   原本把 min/maxDistance 都鎖在 0.01，OrbitControls 的滾輪縮放等於失效，卻還照樣攔截
 *   滾輪事件（頁面也捲不動）。這裡關掉 OrbitControls 的縮放，自己處理滾輪與雙指。
 * · 自動旋轉：碰一下就停，放開 3 秒後恢復；使用者開了「減少動態效果」就預設不轉。
 * · 全螢幕：優先用原生 Fullscreen API；iOS Safari 之類不支援元素全螢幕的，退回 CSS 撐滿視窗。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Icon } from '@iconify/vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const props = defineProps({
  imageUrl: { type: String, required: true },
})

const FOV_MIN = 30
const FOV_MAX = 100
const FOV_DEFAULT = 75
const IDLE_RESUME_MS = 3000

const mq = (q) => (typeof matchMedia === 'function' ? matchMedia(q).matches : false)
const touchUi = mq('(pointer: coarse)')

const wrap = ref(null)
const container = ref(null)
const loading = ref(true)
const error = ref(null)
const autoRotate = ref(!mq('(prefers-reduced-motion: reduce)'))
const hintVisible = ref(true)
const nativeFull = ref(false)
const cssFull = ref(false)
const isFull = computed(() => nativeFull.value || cssFull.value)

let renderer, scene, camera, controls, animId, texture, mesh, resizeObs, idleTimer
let disposed = false
let pinch = null   // { dist, fov }

function clampFov(v) { return Math.min(FOV_MAX, Math.max(FOV_MIN, v)) }

function setFov(v) {
  if (!camera) return
  camera.fov = clampFov(v)
  camera.updateProjectionMatrix()
  controls.rotateSpeed = -0.4 * (camera.fov / FOV_DEFAULT)   // 放大時轉慢一點，才不會一碰就飛掉
}

function dismissHint() { hintVisible.value = false }

function onWheel(e) {
  e.preventDefault()
  setFov(camera.fov + e.deltaY * 0.05)
  dismissHint()
}

const touchDist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
function onTouchStart(e) {
  if (e.touches.length === 2) pinch = { dist: touchDist(e.touches), fov: camera.fov }
}
function onTouchMove(e) {
  if (e.touches.length !== 2 || !pinch) return
  e.preventDefault()
  setFov(pinch.fov * pinch.dist / touchDist(e.touches))   // 雙指張開 = 放大 = 視野角變小
  dismissHint()
}
function onTouchEnd(e) { if (e.touches.length < 2) pinch = null }

function resize() {
  if (!renderer || !container.value) return
  const w = container.value.clientWidth
  const h = container.value.clientHeight
  if (!w || !h) return
  renderer.setSize(w, h)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}

function cleanup() {
  clearTimeout(idleTimer)
  if (animId) cancelAnimationFrame(animId)
  resizeObs?.disconnect()
  if (renderer) {
    const el = renderer.domElement
    el.removeEventListener('wheel', onWheel)
    el.removeEventListener('touchstart', onTouchStart)
    el.removeEventListener('touchmove', onTouchMove)
    el.removeEventListener('touchend', onTouchEnd)
    el.removeEventListener('touchcancel', onTouchEnd)
  }
  controls?.dispose()
  if (mesh) { mesh.geometry.dispose(); mesh.material.dispose() }
  texture?.dispose()
  if (renderer) {
    renderer.dispose()
    if (renderer.domElement.parentNode) renderer.domElement.remove()
  }
  renderer = scene = camera = controls = animId = texture = mesh = resizeObs = undefined
}

async function initViewer() {
  if (!container.value || !props.imageUrl) return
  loading.value = true
  error.value = null

  try {
    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x000000)
    renderer.domElement.style.touchAction = 'none'   // 單指拖曳不要被瀏覽器當成捲頁
    container.value.appendChild(renderer.domElement)

    scene = new THREE.Scene()
    camera = new THREE.PerspectiveCamera(FOV_DEFAULT, 1, 0.1, 2000)
    camera.position.set(0, 0, 0.01)

    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.05
    controls.rotateSpeed = -0.4   // 負值讓拖曳方向符合直覺（像轉頭）
    controls.enableZoom = false   // 縮放改用 FOV，見檔頭說明
    controls.enablePan = false
    controls.autoRotate = autoRotate.value
    controls.autoRotateSpeed = 0.6
    controls.addEventListener('start', () => {
      controls.autoRotate = false
      clearTimeout(idleTimer)
      dismissHint()
    })
    controls.addEventListener('end', () => {
      if (!autoRotate.value) return
      clearTimeout(idleTimer)
      idleTimer = setTimeout(() => { if (controls) controls.autoRotate = true }, IDLE_RESUME_MS)
    })

    const el = renderer.domElement
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd)
    el.addEventListener('touchcancel', onTouchEnd)

    resize()
    resizeObs = new ResizeObserver(resize)
    resizeObs.observe(container.value)

    const tex = await new Promise((resolve, reject) => {
      new THREE.TextureLoader().load(props.imageUrl, resolve, undefined, reject)
    })
    if (disposed) { tex.dispose(); return }
    texture = tex
    texture.colorSpace = THREE.SRGBColorSpace

    // 球體內部投影：SphereGeometry + scale(-1,1,1) 翻轉法向量
    const geo = new THREE.SphereGeometry(500, 72, 40)
    geo.scale(-1, 1, 1)
    mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: texture }))
    scene.add(mesh)

    loading.value = false

    function animate() {
      animId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()
  } catch (e) {
    console.error('[PanoramaViewer]', e)
    error.value = '環景載入失敗，請稍後重試（若問題持續，可能是瀏覽器不支援 WebGL）'
    loading.value = false
  }
}

function toggleRotate() {
  autoRotate.value = !autoRotate.value
  clearTimeout(idleTimer)
  if (controls) controls.autoRotate = autoRotate.value
}

/* ── 全螢幕 ── */
async function toggleFull() {
  if (cssFull.value) { cssFull.value = false; return }
  if (document.fullscreenElement) { await document.exitFullscreen(); return }
  if (document.fullscreenEnabled && wrap.value?.requestFullscreen) {
    try { await wrap.value.requestFullscreen(); return } catch { /* 被拒絕就用 CSS 版 */ }
  }
  cssFull.value = true
}
function onFullChange() { nativeFull.value = document.fullscreenElement === wrap.value; nextResize() }
function onKey(e) { if (e.key === 'Escape' && cssFull.value) cssFull.value = false }
// 版面切換後要等 DOM 套用完才量得到新尺寸（ResizeObserver 也會抓，這裡是保險）
const nextResize = () => requestAnimationFrame(resize)
watch(cssFull, nextResize)

onMounted(() => {
  document.addEventListener('fullscreenchange', onFullChange)
  window.addEventListener('keydown', onKey)
  initViewer()
})
onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('fullscreenchange', onFullChange)
  window.removeEventListener('keydown', onKey)
  if (document.fullscreenElement === wrap.value) document.exitFullscreen?.()
  cleanup()
})
watch(() => props.imageUrl, () => { cleanup(); initViewer() })
</script>

<template>
  <div ref="wrap" class="pv-wrap" :class="{ 'is-full': isFull, 'is-css-full': cssFull }">
    <div ref="container" class="pv-canvas" :class="{ invisible: loading || !!error }"></div>

    <div v-if="loading && !error" class="pv-overlay">
      <div class="pv-spinner"></div>
      <p>載入環景中…</p>
    </div>
    <div v-if="error" class="pv-overlay pv-error">{{ error }}</div>

    <div v-if="!loading && !error" class="pv-tools">
      <button
        type="button" class="pv-btn" :class="{ on: autoRotate }"
        :aria-pressed="autoRotate" :title="autoRotate ? '停止自動旋轉' : '自動旋轉'"
        :aria-label="autoRotate ? '停止自動旋轉' : '自動旋轉'" @click="toggleRotate"
      ><Icon icon="mdi:rotate-360" width="20" /></button>
      <button
        type="button" class="pv-btn"
        :title="isFull ? '離開全螢幕' : '全螢幕'" :aria-label="isFull ? '離開全螢幕' : '全螢幕'" @click="toggleFull"
      ><Icon :icon="isFull ? 'mdi:fullscreen-exit' : 'mdi:fullscreen'" width="22" /></button>
    </div>

    <p v-if="!loading && !error" class="pv-hint" :class="{ hide: !hintVisible }">
      {{ touchUi ? '單指拖曳旋轉・雙指縮放' : '拖曳旋轉・滾輪縮放' }}
    </p>
  </div>
</template>

<style scoped>
.pv-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: 70vh;
  min-height: 260px;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
}
/* 原生全螢幕與 CSS 退路共用：撐滿、去圓角 */
.pv-wrap.is-full { max-height: none; aspect-ratio: auto; border-radius: 0; }
.pv-wrap:fullscreen { width: 100vw; height: 100vh; }
.pv-wrap.is-css-full { position: fixed; inset: 0; z-index: 2000; width: 100vw; height: 100vh; }

/* canvas 容器用 absolute 鋪滿：canvas 自己的像素尺寸不能反過來撐大容器，不然縮放視窗會回饋放大 */
.pv-canvas { position: absolute; inset: 0; }
.pv-canvas :deep(canvas) { display: block; }
.pv-canvas.invisible { visibility: hidden; }

.pv-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: rgba(255,255,255,0.65);
  font-size: 0.9rem;
}
.pv-error { color: #f87171; font-size: 0.85rem; padding: 1.5rem; text-align: center; }

.pv-spinner {
  width: 38px; height: 38px;
  border: 3px solid rgba(255,255,255,0.15);
  border-top-color: var(--db-accent, #c8a97e);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.pv-tools {
  position: absolute;
  top: 10px; right: 10px;
  display: flex;
  gap: 0.4rem;
}
.pv-btn {
  display: grid;
  place-items: center;
  width: 40px; height: 40px;   /* 觸控點擊區至少 40px */
  border: none;
  border-radius: 50%;
  background: rgba(0,0,0,0.5);
  color: rgba(255,255,255,0.85);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.pv-btn:hover { background: rgba(0,0,0,0.75); color: #fff; }
.pv-btn.on { background: var(--db-accent, #c8a97e); color: var(--db-on-accent, #222); }
.pv-btn:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }

.pv-hint {
  position: absolute;
  bottom: 12px; left: 0; right: 0;
  text-align: center;
  font-size: 0.78rem;
  color: rgba(255,255,255,0.7);
  text-shadow: 0 1px 4px rgba(0,0,0,0.6);
  pointer-events: none;
  margin: 0;
  transition: opacity 0.6s;
}
.pv-hint.hide { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .pv-spinner { animation: none; }
}
</style>
