<script setup>
/**
 * 圖上直接編輯：塗抹範圍＋一句需求就能重繪，可切全螢幕。
 * 取代原本結果頁下方那塊要先展開、又把同一張圖再畫一次的微調區。
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import RefineCanvas from '@/components/RefineCanvas.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

const props = defineProps({
  imageUrl:   { type: String, required: true },
  fullscreen: { type: Boolean, default: false },
})
const emit = defineEmits(['update:fullscreen', 'close'])

const {
  brushSize, eraserSize, drawMode, refineCanvasRef, textPrompt,
  submitRefine, undoRefine, canUndoRefine, refining, error,
} = useDesignFlow()

const hasMask = computed(() => !!refineCanvasRef.value?.hasMask)

// 畫筆、橡皮擦各記自己的大小；平移時不顯示滑桿
const size = computed({
  get: () => (drawMode.value === 'erase' ? eraserSize.value : brushSize.value),
  set: (v) => { (drawMode.value === 'erase' ? eraserSize : brushSize).value = v },
})

// 沒塗抹就是整張重繪，第一次按只提示、第二次才送出，免得忘了圈範圍整張被改掉
const confirmWhole = ref(false)
watch(hasMask, () => { confirmWhole.value = false })
async function onSubmit() {
  if (refining.value) return
  if (!hasMask.value && textPrompt.value.trim() && !confirmWhole.value) {
    confirmWhole.value = true
    return
  }
  confirmWhole.value = false
  await submitRefine()
}
const submitLabel = computed(() =>
  hasMask.value ? '重繪塗抹範圍' : confirmWhole.value ? '確定整張重繪？' : '整張重繪',
)

function onKey(e) {
  if (e.key === 'Escape' && props.fullscreen) emit('update:fullscreen', false)
}
window.addEventListener('keydown', onKey)
// 全螢幕時鎖住頁面捲動
watch(() => props.fullscreen, (on) => { document.body.style.overflow = on ? 'hidden' : '' }, { immediate: true })
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>

<template>
  <div class="re" :class="{ 'is-full': fullscreen }">
    <div class="re-stage" :class="{ busy: refining }">
      <RefineCanvas
        ref="refineCanvasRef"
        :image-url="imageUrl"
        :brush-size="size"
        :draw-mode="drawMode"
        :fill="fullscreen"
      >
        <template #corner>
          <button
            type="button"
            :title="fullscreen ? '離開全螢幕（Esc）' : '全螢幕編輯'"
            @click="emit('update:fullscreen', !fullscreen)"
          >{{ fullscreen ? '⤡' : '⛶' }}</button>
          <button type="button" title="結束編輯" @click="emit('close')">✕</button>
        </template>
      </RefineCanvas>
      <div v-if="refining" class="re-busy" role="status">
        <div class="re-spinner"></div>
        <p>AI 重繪中，只會改動塗抹的區域…</p>
      </div>
    </div>

    <div class="re-bar">
      <div class="re-tools">
        <div class="seg" role="group" aria-label="工具">
          <button type="button" :class="{ active: drawMode === 'draw' }" @click="drawMode = 'draw'">畫筆</button>
          <button type="button" :class="{ active: drawMode === 'erase' }" @click="drawMode = 'erase'">橡皮擦</button>
          <button type="button" :class="{ active: drawMode === 'pan' }" @click="drawMode = 'pan'">平移</button>
        </div>
        <template v-if="drawMode !== 'pan'">
          <input v-model.number="size" type="range" min="5" max="120" step="5" class="re-slider" aria-label="筆刷大小" />
          <span class="re-size">{{ size }}px</span>
        </template>
        <button type="button" class="re-link" :disabled="!hasMask" @click="refineCanvasRef?.clearMask()">清除塗抹</button>
        <button v-if="canUndoRefine" type="button" class="re-link" title="回到微調前的圖片" @click="undoRefine">↶ 還原上一版</button>
      </div>

      <form class="re-prompt" @submit.prevent="onSubmit">
        <input
          v-model="textPrompt"
          class="db-input"
          :placeholder="hasMask ? '塗抹的地方要變成什麼？例如：換成藍色布藝沙發' : '先用畫筆圈出要改的地方，再描述想怎麼改'"
          aria-label="微調需求"
        />
        <button class="db-btn" :class="{ warn: confirmWhole }" :disabled="refining">{{ submitLabel }}</button>
      </form>
      <p v-if="confirmWhole" class="re-note">沒有塗抹範圍，會整張重繪。再按一次確認，或先圈出要改的地方。</p>
      <p v-if="error" class="re-error" role="alert">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.re { display: flex; flex-direction: column; gap: 0.9rem; width: 100%; }
.re-stage { position: relative; border-radius: 8px; overflow: hidden; }

.re.is-full {
  position: fixed;
  inset: 0;
  z-index: 1000;
  gap: 0;
  background: #14110e;
}
.re.is-full .re-stage { flex: 1; min-height: 0; border-radius: 0; }
.re.is-full .re-bar { padding: 0.9rem clamp(1rem, 4vw, 2.5rem); background: #fff; }

/* 重繪中：圖模糊、不能再塗，頁面其他部分維持原樣 */
.re-stage.busy :deep(.stage) { filter: blur(6px); transition: filter 0.2s; }
.re-stage.busy :deep(.canvas-root) { pointer-events: none; }
.re-busy {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  background: rgba(20, 18, 14, 0.25);
  color: #fff;
  font-size: 0.9rem;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
}
.re-spinner {
  width: 32px; height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: re-spin 0.8s linear infinite;
}
@keyframes re-spin { to { transform: rotate(360deg); } }

.re-bar { display: flex; flex-direction: column; gap: 0.7rem; }
.re-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }

.seg { display: inline-flex; border-radius: 6px; overflow: hidden; background: var(--db-chip-soft); }
.seg button {
  padding: 0.4rem 0.9rem;
  border: none;
  background: none;
  color: var(--db-text-soft);
  font-size: 0.88rem;
  cursor: pointer;
}
.seg button.active { background: var(--db-accent); color: var(--db-on-accent); cursor: default; }
.seg button:not(.active):hover { background: var(--db-chip); }

.re-slider { width: 9rem; accent-color: var(--db-accent); }
.re-size { min-width: 3.2em; font-size: 0.8rem; color: var(--db-text-soft); font-variant-numeric: tabular-nums; }

.re-link {
  border: none;
  background: none;
  padding: 0;
  color: var(--db-accent-deep);
  font-size: 0.85rem;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.re-link:hover:not(:disabled) { color: var(--db-text); }
.re-link:disabled { opacity: 0.4; cursor: not-allowed; text-decoration: none; }

.re-prompt { display: flex; gap: 0.6rem; }
.re-prompt .db-input { flex: 1; min-width: 0; }
.re-prompt .db-btn { flex-shrink: 0; white-space: nowrap; }
.re-prompt .db-btn.warn { background: #b4572a; color: #fff; }

.re-note, .re-error { margin: 0; font-size: 0.82rem; line-height: 1.5; }
.re-note { color: var(--db-text-soft); }
.re-error { color: #b3261e; }

@media (max-width: 600px) {
  .re-prompt { flex-direction: column; }
  .re-slider { width: 100%; }
}
</style>
