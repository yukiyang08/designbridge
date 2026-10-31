<script setup>
/**
 * 照片入口（租屋族）。還沒上傳時只引導上傳；上傳後白卡最上方是四個功能（修改風格、調整家具位置、
 * 置換或刪除家具、家具估價清單），不必照順序。每個功能都是左邊大圖、右邊控制欄，
 * 版面沿用其他入口的同一功能。每個動作都以目前這一版為底產生新版本。
 */
import { ref, computed, watch } from 'vue'
import { Icon } from '@iconify/vue'
import FurnitureMover from '@/components/FurnitureMover.vue'
import RefineCanvas from '@/components/RefineCanvas.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { adoptPhotoMove } from '@/composables/design-flow/photoLayout'

const {
  spacePhoto, spacePhotoPath, photoDetection, photoLayoutError, photoBusy, photoLayoutLoading,
  photoVersions, photoCurrent, photoStylePrompt, photoQuoting, currentVersion, editableFurniture, styleVersionIndex,
  styleOptions, styleDemoImages,
  uploadPhoto, restylePhoto, refinePhoto, quotePhoto,
} = useDesignFlow()

const TOOLS = [
  { key: 'style',   icon: 'mdi:palette-outline',      title: '修改風格' },
  { key: 'layout',  icon: 'mdi:arrow-all',            title: '調整家具位置' },
  { key: 'replace', icon: 'mdi:swap-horizontal',      title: '置換或刪除家具' },
  { key: 'quote',   icon: 'mdi:receipt-text-outline', title: '家具估價清單' },
]
const hasPhoto = computed(() => !!spacePhotoPath.value && !!photoDetection.value)
const tool = ref('style')
const busy = computed(() => !!photoBusy.value || photoLayoutLoading.value)

function onFile(e) {
  const f = e.target.files?.[0]
  if (!f) return
  spacePhoto.onChange(e)
  tool.value = 'style'
  uploadPhoto(f)
  e.target.value = ''
}

// ── 修改風格 ──
const styles = computed(() => styleOptions.value.filter(o => o.value !== 'auto'))
const styleThumb = (id) => photoVersions.value[styleVersionIndex(id)]?.url || styleDemoImages.value[id]

// ── 調整家具位置：跟結果頁同一套（FurnitureMover），在目前這一版的圖上直接拖家具 ──
// 不帶照片的 scene_graph：後端照「沒有排版相機」的圖處理，家具從圖本身切
const movePlan = computed(() => (currentVersion.value ? { generated_image_path: currentVersion.value.path } : null))

// ── 置換或刪除家具（圖上編輯）──
const canvasRef = ref(null)
const drawMode = ref('draw')
const brushSize = ref(35)
const eraserSize = ref(35)
const size = computed({
  get: () => (drawMode.value === 'erase' ? eraserSize.value : brushSize.value),
  set: (v) => { (drawMode.value === 'erase' ? eraserSize : brushSize).value = v },
})
const refineText = ref('')
const hasMask = computed(() => !!canvasRef.value?.hasMask)
async function onRefine() {
  if (busy.value || !hasMask.value || !refineText.value.trim()) return
  await refinePhoto(await canvasRef.value.getMaskBlob(), refineText.value)
  if (!photoLayoutError.value) refineText.value = ''
}

// ── 家具估價清單 ──
// 打開這一頁或換了版本就估目前這張（已估過的不重打）
watch([tool, photoCurrent], () => { if (tool.value === 'quote') quotePhoto() })
const quotation = computed(() => currentVersion.value?.quotation || null)
const CATEGORY_ZH = {
  sofa: '沙發', table: '桌子', chair: '椅子', lamp: '燈具', rug: '地毯',
  curtain: '窗簾', storage: '收納', shelf: '收納', bed: '床',
}
const shortName = (name = '') => name.split(/[,，]/)[0].trim()
// 有商品圖的才當精準導購（優先選有圖的候選），都沒圖的只列預估價
const quoteRows = computed(() => (quotation.value?.furniture_list || []).map((item, i) => {
  const cands = item.candidates || []
  return { key: i, label: CATEGORY_ZH[item.category] || item.detected_name,
           c: cands.find(c => c?.product_image_url) || cands[0] || null }
}))
const shopRows = computed(() => quoteRows.value.filter(r => r.c?.product_image_url))
const estimateRows = computed(() => quoteRows.value.filter(r => r.c && !r.c.product_image_url))
const quoteTotal = computed(() => quoteRows.value.reduce((s, r) => s + (r.c?.price || 0), 0))
</script>

<template>
  <!-- ══ 還沒有照片：只引導上傳 ══ -->
  <div v-if="!hasPhoto" class="ps-intro">
    <label class="drop" :class="{ busy }">
      <input type="file" accept="image/*" hidden :disabled="busy" @change="onFile" />
      <template v-if="!busy">
        <span class="drop-icon">📷</span>
        <span class="drop-label">先上傳你現在的房間照片</span>
        <small class="drop-hint">JPG、PNG、WebP，盡量拍到地板與整面牆</small>
        <span class="db-btn drop-btn">選擇照片</span>
      </template>
      <template v-else>
        <div class="spinner"></div>
        <span class="drop-hint">{{ photoBusy || 'AI 處理中…' }}</span>
      </template>
    </label>
    <p v-if="photoLayoutError" class="db-error">{{ photoLayoutError }}</p>
    <ul class="intro-features" aria-label="上傳後可以做的事">
      <li v-for="t in TOOLS" :key="t.key"><Icon :icon="t.icon" width="18" />{{ t.title }}</li>
    </ul>
  </div>

  <!-- ══ 有照片：功能列＋工作區 ══ -->
  <div v-else class="ps">
    <div class="ps-top">
      <nav class="ps-tabs" role="tablist" aria-label="功能">
        <button
          v-for="t in TOOLS" :key="t.key" type="button" role="tab" class="ps-tab"
          :class="{ active: tool === t.key }" :aria-selected="tool === t.key" @click="tool = t.key"
        >
          <Icon :icon="t.icon" width="20" />
          <span>{{ t.title }}</span>
        </button>
      </nav>
      <label class="change-photo" :class="{ disabled: busy }" title="換一張照片會重新開始">
        <input type="file" accept="image/*" hidden :disabled="busy" @change="onFile" />
        <Icon icon="mdi:camera-retake-outline" width="18" />換照片
      </label>
    </div>

    <p v-if="photoLayoutError" class="db-error ps-error">{{ photoLayoutError }}</p>

    <div class="ps-work">
      <!-- 左：大圖 -->
      <section class="ps-main">
        <div class="stage" :class="{ 'stage--canvas': tool === 'replace', 'stage--mover': tool === 'layout' }">
          <FurnitureMover
            v-if="tool === 'layout' && movePlan"
            :key="currentVersion.path"
            :image-url="currentVersion.url"
            :plan="movePlan"
            @applied="adoptPhotoMove"
            @close="tool = 'style'"
          />
          <RefineCanvas
            v-else-if="tool === 'replace'"
            ref="canvasRef" fill :image-url="currentVersion.url" :brush-size="size" :draw-mode="drawMode"
          />
          <img v-else :src="currentVersion.url" :alt="currentVersion.label" class="stage-img" />

          <div v-if="busy" class="ps-busy" role="status">
            <div class="spinner"></div>
            <p>{{ photoBusy || 'AI 處理中…' }}</p>
          </div>
        </div>

        <!-- 每次生成的版本，可以切回去比較或接著改 -->
        <div v-if="photoVersions.length > 1" class="versions" aria-label="版本">
          <button
            v-for="(v, i) in photoVersions" :key="v.path" type="button" class="ver"
            :class="{ active: i === photoCurrent }" :disabled="busy" :title="v.label"
            @click="photoCurrent = i"
          >
            <img :src="v.url" :alt="v.label" />
            <span>{{ v.label }}</span>
          </button>
        </div>
      </section>

      <!-- 右：控制欄 -->
      <aside class="ps-side">
        <!-- 修改風格 -->
        <template v-if="tool === 'style'">
          <label class="field-label" for="style-prompt">想要什麼風格？</label>
          <textarea
            id="style-prompt" v-model="photoStylePrompt" class="db-textarea style-prompt" rows="3"
            placeholder="用一句話描述你想要的樣子，例如：溫暖的木質感、明亮的白色系"
          />
          <button type="button" class="db-btn" :disabled="busy || !photoStylePrompt.trim()" @click="restylePhoto()">
            依描述生成
          </button>
          <p class="side-note">家具位置不變，只換裝潢風格。</p>

          <h3 class="side-title">或直接選一個風格</h3>
          <div class="swap-grid">
            <button
              type="button" class="swap-card generated" :class="{ active: photoCurrent === 0 }"
              :disabled="busy" title="回到原照片" @click="photoCurrent = 0"
            >
              <span class="swap-thumb"><img :src="photoVersions[0].url" alt="原照片" /></span>
              <span class="swap-label">原照片</span>
            </button>
            <button
              v-for="s in styles" :key="s.value" type="button" class="swap-card"
              :class="{ active: currentVersion.styleId === s.value, generated: styleVersionIndex(s.value) >= 0 }"
              :disabled="busy"
              :title="styleVersionIndex(s.value) >= 0 ? `${s.name}，已生成，點一下切換` : `${s.name}，點一下生成`"
              @click="restylePhoto(s.value)"
            >
              <span class="swap-thumb">
                <img v-if="styleThumb(s.value)" :src="styleThumb(s.value)" :alt="s.name" />
                <span v-else class="swap-thumb-empty">＋</span>
                <span v-if="styleVersionIndex(s.value) >= 0" class="swap-done" aria-label="已生成">✓</span>
              </span>
              <span class="swap-label">{{ s.name }}</span>
            </button>
          </div>
        </template>

        <!-- 調整家具位置 -->
        <template v-else-if="tool === 'layout'">
          <h3 class="side-title">✥ 移動家具</h3>
          <p class="side-note">在左邊圖上直接拖曳家具到新位置，可以一次搬好幾件，按「套用」後 AI 會補上原位置並融合光影。</p>
          <p class="side-note">第一次會先辨識圖上的家具，約需 40 秒。每次套用都會多一個版本，可以從下方版本列切回去比較。</p>
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
          <button type="button" class="re-link" :disabled="!hasMask" @click="canvasRef?.clearMask()">清除塗抹</button>
          <template v-if="editableFurniture.length">
            <h3 class="side-title">快速圈選</h3>
            <div class="chips">
              <button
                v-for="f in editableFurniture" :key="f.id" type="button" class="chip"
                @click="canvasRef?.paintBox(f.box)"
              >{{ f.label }}</button>
            </div>
          </template>
          <label class="field-label" for="refine-text">要怎麼改？</label>
          <textarea
            id="refine-text" v-model="refineText" class="db-textarea" rows="2"
            :placeholder="hasMask ? '例如：刪除、換成淺灰布沙發' : '先在左邊圖上圈出要改的家具'"
          />
          <button type="button" class="db-btn" :disabled="busy || !hasMask || !refineText.trim()" @click="onRefine">執行細節調整</button>
        </template>

        <!-- 家具估價清單 -->
        <template v-else>
          <div class="quote-head">
            <h3 class="side-title">家具估價清單</h3>
            <button
              v-if="quotation" type="button" class="re-link" :disabled="photoQuoting"
              @click="quotePhoto(true)"
            >重新估價</button>
          </div>
          <p class="side-note">依左邊目前這張圖辨識家具並推薦商品。</p>
          <p v-if="photoQuoting" class="side-note" role="status">估價中，約 30 秒…</p>
          <p v-else-if="currentVersion.quoteError" class="db-error">{{ currentVersion.quoteError }}</p>
          <template v-if="quotation">
            <div class="quote-total">
              <span>預算 · {{ quoteRows.length }} 件</span>
              <strong>NT$ {{ quoteTotal.toLocaleString() }}</strong>
            </div>
            <ul v-if="shopRows.length" class="quote-list">
              <li v-for="r in shopRows" :key="r.key" class="quote-item">
                <span class="q-thumb">
                  <img :src="r.c.product_image_url" :alt="r.c.name" />
                </span>
                <span class="q-info">
                  <small>{{ r.label }}</small>
                  <a v-if="r.c.purchase_url" :href="r.c.purchase_url" target="_blank" rel="noopener" :title="r.c.name">{{ shortName(r.c.name) }}</a>
                  <span v-else>{{ shortName(r.c.name) }}</span>
                </span>
                <span class="q-price">NT$ {{ (r.c.price || 0).toLocaleString() }}</span>
              </li>
            </ul>
            <template v-if="estimateRows.length">
              <h4 class="q-sub">預估估價項目</h4>
              <ul class="quote-list">
                <li v-for="r in estimateRows" :key="r.key" class="quote-item q-est">
                  <span class="q-info">
                    <small>{{ r.label }}</small>
                    <span :title="r.c.name">{{ shortName(r.c.name) || '—' }}</span>
                  </span>
                  <span class="q-price">NT$ {{ (r.c.price || 0).toLocaleString() }}</span>
                </li>
              </ul>
            </template>
          </template>
        </template>
      </aside>
    </div>
  </div>
</template>

<style scoped>
/* ── 上傳引導 ── */
.ps-intro { display: flex; flex-direction: column; gap: 1rem; padding-bottom: 1.5rem; }
.drop {
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.7rem;
  min-height: max(360px, calc(100vh - 360px));
  border: 2px dashed #cfcfcf; border-radius: 8px; background: var(--db-chip); cursor: pointer;
  transition: background 0.16s, border-color 0.16s;
}
.drop:hover:not(.busy) { background: #cfcfcf; border-color: var(--db-accent); }
.drop.busy { cursor: progress; }
.drop-icon { font-size: 2.8rem; }
.drop-label { font-family: var(--db-font-display); font-size: 1.7rem; color: var(--db-text); }
.drop-hint { color: var(--db-text-soft); font-size: 0.9rem; }
.drop-btn { margin-top: 0.4rem; pointer-events: none; }
.intro-features { display: flex; justify-content: center; flex-wrap: wrap; gap: 0.5rem 1.5rem; margin: 0; padding: 0; list-style: none; }
.intro-features li { display: inline-flex; align-items: center; gap: 0.35rem; color: var(--db-text-soft); font-size: 0.9rem; }

/* ── 工作台：圖片優先，矮螢幕寧可捲一點也不壓扁圖 ── */
.ps {
  --ps-h: max(560px, calc(100vh - 230px));
  display: flex; flex-direction: column; gap: 0.75rem; height: var(--ps-h); padding-bottom: 0.75rem;
}
.ps-top { display: flex; align-items: center; gap: 1rem; flex-shrink: 0; }
.ps-tabs { flex: 1; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.5rem; }
.ps-tab {
  display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  padding: 0.7rem 0.75rem; border: 1px solid #e5e1d8; border-radius: var(--db-radius-pill, 999px);
  background: #fff; color: var(--db-text); font: inherit; font-size: clamp(0.82rem, 1.1vw, 0.98rem); cursor: pointer; min-width: 0;
  transition: background 0.16s, border-color 0.16s, color 0.16s;
}
.ps-tab:hover:not(.active) { border-color: var(--db-accent); background: #f7f6f3; }
.ps-tab span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ps-tab.active { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent, #fff); }
/* 換照片是次要動作：文字連結樣式，不跟四個功能長得一樣 */
.change-photo {
  flex-shrink: 0; display: inline-flex; align-items: center; gap: 0.3rem;
  color: var(--db-text-soft); font-size: 0.88rem; text-decoration: underline; text-underline-offset: 3px; cursor: pointer;
}
.change-photo:hover { color: var(--db-text); }
.change-photo.disabled { opacity: 0.4; pointer-events: none; }
.ps-error { margin: 0; }

.ps-work { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) clamp(260px, 26vw, 380px); gap: 1.25rem; }
.ps-main { min-height: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.stage {
  position: relative; flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center;
  border-radius: 8px; background: var(--db-chip-soft); overflow: hidden;
}
.stage-img { max-width: 100%; max-height: 100%; object-fit: contain; }
.stage--canvas { background: #1a0d08; }
.stage--mover { align-items: stretch; }
.stage--mover :deep(.fm-img) { max-height: calc(var(--ps-h) - 90px); }

/* ── 右側控制欄 ── */
.ps-side { min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 0.7rem; padding-right: 2px; }
.field-label { font-size: 0.95rem; font-weight: 600; color: var(--db-text); }
.style-prompt { min-height: 96px; background: #fff; border: 2px solid #756d66; font-size: 0.95rem; }
.style-prompt:focus { outline: none; box-shadow: 0 0 0 3px var(--db-accent-soft); }
.side-title { margin: 0.4rem 0 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: 1.05rem; color: var(--db-text); }
.side-note { margin: 0; font-size: 0.82rem; color: var(--db-text-soft); line-height: 1.6; }
.side-actions { display: flex; gap: 0.5rem; }
.side-actions .db-btn { flex: 1; min-width: 0; }
.ref-photo { width: 100%; border-radius: 8px; }

/* 一鍵換風格卡片（同 StepResult，改成直排網格） */
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

/* 圖上編輯工具（同 RefineEditor） */
.re-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; }
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
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip {
  padding: 0.25rem 0.7rem; border: 1px solid #e2ddd4; border-radius: 999px; background: #fff;
  font: inherit; font-size: 0.82rem; cursor: pointer;
}
.chip:hover { border-color: var(--db-accent); }

/* 估價清單（同結果頁的家具推薦） */
.quote-head { display: flex; align-items: baseline; justify-content: space-between; }
.quote-total {
  display: flex; align-items: baseline; justify-content: space-between; padding: 0.6rem 0.8rem;
  border-radius: 8px; background: var(--db-chip-soft); font-size: 0.88rem; color: var(--db-text-soft);
}
.quote-total strong { font-size: 1.15rem; color: var(--db-text); }
.quote-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 0.5rem; }
.quote-item { display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; align-items: center; gap: 0.6rem; }
.q-thumb { width: 48px; height: 48px; border-radius: 6px; overflow: hidden; background: #f1eee8; }
.q-thumb img { width: 100%; height: 100%; object-fit: cover; }
.q-info { display: flex; flex-direction: column; min-width: 0; font-size: 0.86rem; }
.q-info small { color: var(--db-text-soft); font-size: 0.74rem; }
.q-info a, .q-info span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--db-text); }
.q-price { font-size: 0.86rem; font-variant-numeric: tabular-nums; }
.q-sub { margin: 0.6rem 0 0.1rem; font-size: 0.78rem; font-weight: 600; color: var(--db-text-soft); letter-spacing: 0.04em; }
.q-est { grid-template-columns: minmax(0, 1fr) auto; }   /* 預估項目沒有縮圖欄 */

/* ── 版本 ── */
.versions { display: flex; gap: 0.5rem; overflow-x: auto; flex-shrink: 0; padding-bottom: 2px; }
.ver {
  flex: 0 0 auto; display: flex; flex-direction: column; gap: 2px; width: 88px; padding: 3px;
  border: 2px solid transparent; border-radius: 8px; background: #fff; cursor: pointer; text-align: left;
}
.ver img { width: 100%; height: 46px; object-fit: cover; border-radius: 5px; }
.ver span { font-size: 0.7rem; color: var(--db-text-soft); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ver.active { border-color: var(--db-accent); }

/* ── 處理中 ── */
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
  .ps-top { flex-direction: column; align-items: stretch; }
  .ps-tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ps-work { grid-template-columns: 1fr; }
  .stage { min-height: 360px; }
  .ps-side { overflow: visible; }
}
</style>
