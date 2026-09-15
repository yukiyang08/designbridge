<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const props = defineProps({
  imageUrl: { type: String, required: true },
})

const container = ref(null)
const loading = ref(true)
const error = ref(null)

let renderer, scene, camera, controls, animId

function cleanup() {
  if (animId) cancelAnimationFrame(animId)
  if (controls) controls.dispose()
  if (renderer) {
    renderer.dispose()
    if (renderer.domElement.parentNode) renderer.domElement.remove()
  }
  renderer = scene = camera = controls = animId = null
}

async function initViewer() {
  if (!container.value || !props.imageUrl) return
  loading.value = true
  error.value = null

  try {
    const W = container.value.clientWidth || 800
    const H = container.value.clientHeight || 520

    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(W, H)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x000000)
    container.value.appendChild(renderer.domElement)

    scene = new THREE.Scene()
    camera = new THREE.PerspectiveCamera(75, W / H, 0.1, 2000)
    camera.position.set(0, 0, 0.01)

    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.05
    controls.rotateSpeed = -0.4   // 負值讓拖曳方向符合直覺（像轉頭）
    controls.enableZoom = true
    controls.minDistance = 0.01
    controls.maxDistance = 0.01   // 鎖定在球心，只能旋轉

    const texture = await new Promise((resolve, reject) => {
      new THREE.TextureLoader().load(props.imageUrl, resolve, undefined, reject)
    })
    texture.colorSpace = THREE.SRGBColorSpace

    // 球體內部投影：SphereGeometry + scale(-1,1,1) 翻轉法向量
    const geo = new THREE.SphereGeometry(500, 72, 40)
    geo.scale(-1, 1, 1)
    const mat = new THREE.MeshBasicMaterial({ map: texture })
    scene.add(new THREE.Mesh(geo, mat))

    loading.value = false

    function animate() {
      animId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()
  } catch (e) {
    console.error('[PanoramaViewer]', e)
    error.value = '全景圖載入失敗：' + e.message
    loading.value = false
  }
}

onMounted(initViewer)
onUnmounted(cleanup)
watch(() => props.imageUrl, () => { cleanup(); initViewer() })
</script>

<template>
  <div class="pv-wrap">
    <div v-if="loading && !error" class="pv-overlay">
      <div class="pv-spinner"></div>
      <p>載入全景圖中…</p>
    </div>
    <div v-if="error" class="pv-overlay pv-error">{{ error }}</div>
    <div ref="container" class="pv-canvas" :class="{ invisible: loading || !!error }"></div>
    <p v-if="!loading && !error" class="pv-hint">拖曳旋轉視角・滾輪縮放</p>
  </div>
</template>

<style scoped>
.pv-wrap {
  position: relative;
  width: 100%;
  height: 520px;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
}
.pv-canvas { width: 100%; height: 100%; }
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
  border-top-color: #c8a97e;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.pv-hint {
  position: absolute;
  bottom: 10px; left: 0; right: 0;
  text-align: center;
  font-size: 0.7rem;
  color: rgba(255,255,255,0.35);
  pointer-events: none;
  margin: 0;
}
</style>
