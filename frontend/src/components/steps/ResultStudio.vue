<script setup>
/**
 * 不排家具路徑生成後的工作台：跟照片入口（StepPhotoStudio）同一套版面，
 * 上方四個功能分頁、左邊大圖、右邊控制欄；功能本身沿用結果頁的換風格、移家具、微調、估價。
 */
import { ref, computed, watch } from 'vue'
import { Icon } from '@iconify/vue'
import FurnitureMover from '@/components/FurnitureMover.vue'
import RefineCanvas from '@/components/RefineCanvas.vue'
import QuotationPanel from '@/components/QuotationPanel.vue'
import TimingPanel from '@/components/TimingPanel.vue'
import { canMoveFurniture, canUndoMove, undoMove, applyingMove } from '@/composables/design-flow/move'
import { useDesignFlow, ORIGINAL_STYLE_KEY } from '@/composables/useDesignFlow'

const {
  result, styleOptions, styleDemoImages, styleSwapCache, swappingStyle, swapStyle, restoreOriginal,
  brushSize, eraserSize, drawMode, refineCanvasRef, textPrompt,
  submitRefine, undoRefine, canUndoRefine, refining, error,
} = useDesignFlow()

const TOOLS = [
  { key: 'style',   icon: 'mdi:palette-outline',      title: '修改風格' },
  { key: 'layout',  icon: 'mdi:arrow-all',            title: '調整家具位置' },
  { key: 'replace', icon: 'mdi:swap-horizontal',      title: '置換或刪除家具' },
  { key: 'quote',   icon: 'mdi:receipt-text-outline', title: '家具估價清單' },
]
const tool = ref('style')
const imageUrl = computed(() => result.value?.generated_image_url || '')
const busy = computed(() => swappingStyle.value || refining.value || applyingMove.value)
const busyText = computed(() => (swappingStyle.value ? '風格變換中…' : refining.value ? 'AI 重繪中，只會改動塗抹的區域…' : ''))

// ── 修改風格 ──
const styles = computed(() => styleOptions.value.filter(o => o.value !== 'auto'))
const activeStyleId = computed(() => result.value?.style_params?.style_profile_id)
const original = computed(() => styleSwapCache.value[ORIGINAL_STYLE_KEY])
const isOriginalActive = computed(() => !!result.value && result.value === original.value)
const styleThumb = (id) => styleSwapCache.value[id]?.generated_image_url || styleDemoImages.value[id]

// ── 置換或刪除家具（圖上編輯）──
const size = computed({
  get: () => (drawMode.value === 'erase' ? eraserSize.value : brushSize.value),
  set: (v) => { (drawMode.value === 'erase' ? eraserSize : brushSize).value = v },
})
const hasMask = computed(() => !!refineCanvasRef.value?.hasMask)
async function onRefine() {
  if (busy.value || !hasMask.value || !textPrompt.value.trim()) return
  await submitRefine()
  if (!error.value) textPrompt.value = ''
}
// 切分頁就不留舊的錯誤訊息
watch(tool, () => { error.value = '' })

// ── 耗時 ──
const showTimings = ref(false)
const timingRuns = computed(() => {
  const r = result.value
  if (r?.timing_runs?.length) return r.timing_runs
  if (!r?.timings?.length) return []
  return [{ kind: r.routing_decision === 'design_adjuster' ? 'refine' : 'generate', elapsed_seconds: parseFloat(r.elapsed_time) || 0, timings: r.timings }]
})
</script>

<template>
  <div class="ps">
    <nav class="ps-tabs" role="tablist" aria-label="功能">
      <button
        v-for="t in TOOLS" :key="t.key" type="button" role="tab" class="ps-tab"
        :class="{ active: tool === t.key }" :aria-selected="tool === t.key" @click="tool = t.key"
      >
        <Icon :icon="t.icon" width="20" />
        <span>{{ t.title }}</span>
      </button>
    </nav>

    <p v-if="error && tool === 'replace'" class="db-error ps-error">{{ error }}</p>

    <div class="ps-work">
      <!-- 左：大圖 -->
      <section class="ps-main">
        <div class="stage" :class="{ 'stage--canvas': tool === 'replace', 'stage--mover': tool === 'layout' && canMoveFurniture }">
          <FurnitureMover
            v-if="tool === 'layout' && canMoveFurniture && imageUrl"
            :image-url="imageUrl"
            @close="tool = 'style'"
          />
          <RefineCanvas
            v-else-if="tool === 'replace' && imageUrl"
            ref="refineCanvasRef" fill :image-url="imageUrl" :brush-size="size" :draw-mode="drawMode"
          />
          <img v-else-if="imageUrl" :src="imageUrl" alt="生成的 3D 渲染圖" class="stage-img" />
          <p v-else class="side-note">生成完成，但沒有取得圖片 URL。</p>

          <button
            v-if="tool !== 'layout' && timingRuns.length" type="button" class="timing-btn"
            title="各環節耗時" aria-label="查看各環節耗時" @click="showTimings = true"
          >
            <Icon icon="mdi:clock-outline" width="18" />
          </button>

          <div v-if="busyText" class="ps-busy" role="status">
            <div class="spinner"></div>
            <p>{{ busyText }}</p>
          </div>
        </div>
      </section>

      <!-- 右：控制欄 -->
      <aside class="ps-side">
        <!-- 修改風格：沿用同一個房間佈局／視角，只換風格重繪 -->
        <template v-if="tool === 'style'">
          <h3 class="side-title">選一個風格</h3>
          <p class="side-note">家具位置不變，只換裝潢風格。已生成過的風格點一下直接切換。</p>
          <div class="swap-grid">
            <button
              v-if="original" type="button" class="swap-card generated" :class="{ active: isOriginalActive }"
              :disabled="busy" title="回到最一開始生成的那張" @click="restoreOriginal"
            >
              <span class="swap-thumb"><img :src="original.generated_image_url" alt="原圖" /></span>
              <span class="swap-label">原圖</span>
            </button>
            <button
              v-for="s in styles" :key="s.value" type="button" class="swap-card"
              :class="{ active: activeStyleId === s.value, generated: !!styleSwapCache[s.value] }"
              :disabled="busy"
              :title="styleSwapCache[s.value] ? `${s.name}，已生成，點一下切換` : `${s.name}，點一下生成`"
              @click="swapStyle(s.value)"
            >
              <span class="swap-thumb">
                <img v-if="styleThumb(s.value)" :src="styleThumb(s.value)" :alt="s.name" />
                <span v-else class="swap-thumb-empty">＋</span>
                <span v-if="styleSwapCache[s.value]" class="swap-done" aria-label="已生成">✓</span>
              </span>
              <span class="swap-label">{{ s.name }}</span>
            </button>
          </div>
        </template>

        <!-- 調整家具位置 -->
        <template v-else-if="tool === 'layout'">
          <h3 class="side-title">✥ 移動家具</h3>
          <template v-if="canMoveFurniture">
            <p class="side-note">在左邊圖上直接拖曳家具到新位置，可以一次搬好幾件，按「套用」後 AI 會補上原位置並融合光影。</p>
            <p class="side-note">第一次會先辨識圖上的家具，約需 40 秒。</p>
            <button v-if="canUndoMove" type="button" class="re-link" :disabled="busy" @click="undoMove">↶ 復原上一次移動</button>
          </template>
          <p v-else class="side-note">這張圖目前不能移動家具。</p>
        </template>

        <!-- 置換或刪除家具 -->
        <template v-else-if="tool === 'replace'">
          <div class="re-tools">
            <div class="seg" role="group" aria-label="工具">
              <button type="button" :class="{ active: drawMode === 'draw' }" @click="drawMode = 'draw'">畫筆</button>
              <button type="button" :class="{ active: drawMode === 'erase' }" @click="drawMode = 'erase'">橡皮擦</button>
            </div>
            <input v-model.number="size" type="range" min="5" max="120" step="5" class="re-slider" aria-label="筆刷大小" />
            <span class="re-size">{{ size }}px</span>
          </div>
          <div class="re-links">
            <button type="button" class="re-link" :disabled="!hasMask" @click="refineCanvasRef?.clearMask()">清除塗抹</button>
            <button v-if="canUndoRefine" type="button" class="re-link" :disabled="busy" @click="undoRefine">↶ 還原上一版</button>
          </div>
          <label class="field-label" for="refine-text">要怎麼改？</label>
          <textarea
            id="refine-text" v-model="textPrompt" class="db-textarea" rows="2"
            :placeholder="hasMask ? '例如：刪除、換成淺灰布沙發' : '先在左邊圖上圈出要改的家具'"
          />
          <button type="button" class="db-btn" :disabled="busy || !hasMask || !textPrompt.trim()" @click="onRefine">執行細節調整</button>
        </template>

        <!-- 家具估價清單：出圖後就自動估價（StepResult），這裡只顯示 -->
        <QuotationPanel v-else class="quote" />
      </aside>
    </div>

    <TimingPanel v-if="showTimings && timingRuns.length" :runs="timingRuns" @close="showTimings = false" />
  </div>
</template>

<style scoped>
/* 版面同 StepPhotoStudio：圖片優先，矮螢幕寧可捲一點也不壓扁圖 */
.ps {
  --ps-h: max(560px, calc(100vh - 230px));
  display: flex; flex-direction: column; gap: 0.75rem; height: var(--ps-h); padding-bottom: 0.75rem;
}
.ps-tabs { flex-shrink: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.5rem; }
.ps-tab {
  display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  padding: 0.7rem 0.75rem; border: 1px solid #e5e1d8; border-radius: var(--db-radius-pill, 999px);
  background: #fff; color: var(--db-text); font: inherit; font-size: clamp(0.82rem, 1.1vw, 0.98rem); cursor: pointer; min-width: 0;
  transition: background 0.16s, border-color 0.16s, color 0.16s;
}
.ps-tab:hover:not(.active) { border-color: var(--db-accent); background: #f7f6f3; }
.ps-tab span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ps-tab.active { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent, #fff); }
.ps-error { margin: 0; }

.ps-work { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) clamp(280px, 27vw, 400px); gap: 1.25rem; }
.ps-main { min-height: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.stage {
  position: relative; flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center;
  border-radius: 8px; background: var(--db-chip-soft); overflow: hidden;
}
.stage-img { max-width: 100%; max-height: 100%; object-fit: contain; }
.stage--canvas { background: #1a0d08; }
/* 圖下方還有分頁列與移動工具列，要先扣掉，圖才不會把工具列擠出框外 */
.stage--mover { align-items: stretch; overflow-y: auto; }
.stage--mover :deep(.fm-img) { max-height: calc(var(--ps-h) - 160px); }
.timing-btn {
  position: absolute; right: 0.75rem; bottom: 0.75rem; z-index: 3; display: grid; place-items: center;
  width: 34px; height: 34px; border: none; border-radius: 50%;
  background: rgba(20, 18, 14, 0.62); color: #fff; cursor: pointer; transition: background 0.16s;
}
.timing-btn:hover { background: rgba(20, 18, 14, 0.9); }

/* ── 右側控制欄 ── */
.ps-side { min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 0.7rem; padding-right: 2px; }
.field-label { font-size: 0.95rem; font-weight: 600; color: var(--db-text); }
.side-title { margin: 0.4rem 0 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: 1.05rem; color: var(--db-text); }
.side-note { margin: 0; font-size: 0.82rem; color: var(--db-text-soft); line-height: 1.6; }
.quote { flex-shrink: 0; }

.swap-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.5rem; }
.swap-card {
  display: flex; flex-direction: column; align-items: center; gap: 0.3rem; min-width: 0;
  padding: 0; border: none; background: none; font-family: var(--db-font-body); cursor: pointer;
}
.swap-thumb {
  position: relative; display: grid; place-items: center; width: 100%; aspect-ratio: 1;
  border-radius: 12px; overflow: hidden; border: 2px solid #ececec; background: #f5f3ee;
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;
}
.swap-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.swap-thumb-empty { font-size: 1.4rem; color: var(--db-placeholder); }
.swap-done {
  position: absolute; top: 4px; right: 4px; width: 18px; height: 18px; border-radius: 50%;
  display: grid; place-items: center; background: var(--db-accent); color: #fff; font-size: 0.7rem; line-height: 1;
}
.swap-card:hover:not(:disabled) .swap-thumb { border-color: var(--db-accent); }
.swap-card.active .swap-thumb { border-color: var(--db-accent); box-shadow: 0 0 0 3px var(--db-accent-soft); }
.swap-label { font-size: 0.78rem; color: var(--db-text-soft); text-align: center; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.swap-card.active .swap-label { color: var(--db-text); font-weight: 600; }
.swap-card:disabled { opacity: 0.6; cursor: not-allowed; }

.re-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; }
.re-links { display: flex; gap: 1rem; }
.seg { display: inline-flex; border-radius: 6px; overflow: hidden; background: var(--db-chip-soft); }
.seg button { padding: 0.4rem 0.9rem; border: none; background: none; color: var(--db-text-soft); font-size: 0.88rem; cursor: pointer; }
.seg button.active { background: var(--db-accent); color: var(--db-on-accent, #fff); cursor: default; }
.seg button:not(.active):hover { background: var(--db-chip); }
.re-slider { flex: 1; min-width: 80px; accent-color: var(--db-accent); }
.re-size { min-width: 3.2em; font-size: 0.8rem; color: var(--db-text-soft); font-variant-numeric: tabular-nums; }
.re-link {
  align-self: flex-start; border: none; background: none; padding: 0; color: var(--db-accent-deep); font-size: 0.85rem;
  text-decoration: underline; text-underline-offset: 3px; cursor: pointer;
}
.re-link:disabled { opacity: 0.4; cursor: not-allowed; text-decoration: none; }

.ps-busy {
  position: absolute; inset: 0; z-index: 5; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.5rem; background: rgba(255, 255, 255, 0.7); backdrop-filter: blur(2px);
}
.ps-busy p { margin: 0; padding: 0.3rem 0.9rem; border-radius: 999px; background: rgba(255, 255, 255, 0.9); font-weight: 600; }
.spinner {
  width: 34px; height: 34px; border-radius: 50%; border: 3px solid #e5e1d8; border-top-color: var(--db-accent);
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 760px) {
  .ps { height: auto; }
  .ps-tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ps-work { grid-template-columns: 1fr; }
  .stage { min-height: 360px; }
  .ps-side { overflow: visible; }
}
</style>
