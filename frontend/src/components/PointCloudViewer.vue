<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

const props = defineProps({
  plyUrl: { type: String, required: true },
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
  if (!container.value || !props.plyUrl) return
  loading.value = true
  error.value = null

  try {
    const W = container.value.clientWidth || 800
    const H = container.value.clientHeight || 520

    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(W, H)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x0d0d18)
    container.value.appendChild(renderer.domElement)

    scene = new THREE.Scene()
    camera = new THREE.PerspectiveCamera(60, W / H, 0.001, 200)

    controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.06

    const loader = new PLYLoader()
    const geometry = await new Promise((resolve, reject) => {
      loader.load(props.plyUrl, resolve, undefined, reject)
    })

    geometry.computeBoundingBox()
    const center = new THREE.Vector3()
    geometry.boundingBox.getCenter(center)
    geometry.translate(-center.x, -center.y, -center.z)

    const bbox = new THREE.Box3().setFromBufferAttribute(geometry.attributes.position)
    const size = bbox.getSize(new THREE.Vector3()).length()

    let mesh
    if (geometry.index) {
      // Mesh PLY (has faces) — solid surface, no holes in smooth areas
      const material = new THREE.MeshBasicMaterial({
        vertexColors: true,
        side: THREE.DoubleSide,
      })
      mesh = new THREE.Mesh(geometry, material)
    } else {
      // Point cloud PLY fallback
      const material = new THREE.PointsMaterial({
        size: Math.max(0.012, size * 0.005),
        vertexColors: true,
        sizeAttenuation: true,
      })
      mesh = new THREE.Points(geometry, material)
    }
    mesh.rotation.x = Math.PI  // flip Y: image-down → 3D-up
    scene.add(mesh)

    // Position camera in FRONT of scene (negative Z = original photo side)
    // with slight upward tilt so the room looks 3D from the start
    camera.position.set(size * 0.15, -size * 0.12, -size * 0.45)
    controls.target.set(0, 0, 0)
    controls.update()

    loading.value = false

    function animate() {
      animId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()
  } catch (e) {
    console.error('[PointCloudViewer]', e)
    error.value = '點雲載入失敗：' + e.message
    loading.value = false
  }
}

onMounted(initViewer)
onUnmounted(cleanup)
watch(() => props.plyUrl, () => { cleanup(); initViewer() })
</script>

<template>
  <div class="pcv-wrap">
    <div v-if="loading && !error" class="pcv-overlay">
      <div class="pcv-spinner"></div>
      <p>載入點雲中…</p>
    </div>
    <div v-if="error" class="pcv-overlay pcv-error">{{ error }}</div>
    <div ref="container" class="pcv-canvas" :class="{ invisible: loading || !!error }"></div>
    <p v-if="!loading && !error" class="pcv-hint">拖曳旋轉・滾輪縮放・右鍵平移</p>
  </div>
</template>

<style scoped>
.pcv-wrap {
  position: relative;
  width: 100%;
  height: 520px;
  border-radius: 12px;
  overflow: hidden;
  background: #0d0d18;
}
.pcv-canvas { width: 100%; height: 100%; }
.pcv-canvas.invisible { visibility: hidden; }

.pcv-overlay {
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
.pcv-error { color: #f87171; font-size: 0.85rem; padding: 1.5rem; text-align: center; }

.pcv-spinner {
  width: 38px; height: 38px;
  border: 3px solid rgba(255,255,255,0.15);
  border-top-color: #c8a97e;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.pcv-hint {
  position: absolute;
  bottom: 10px; left: 0; right: 0;
  text-align: center;
  font-size: 0.7rem;
  color: rgba(255,255,255,0.3);
  pointer-events: none;
  margin: 0;
}
</style>
