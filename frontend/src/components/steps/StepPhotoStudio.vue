<script setup>
/**
 * 照片入口（租屋族）：一頁完成四件事——上傳照片、換風格（家具不動）、調整家具位置、換／刪家具。
 * 左邊是目前這一版的圖與歷史版本，右邊四個功能區塊；每個動作都以目前這一版為底產生新版本。
 * 調整家具位置時左邊大畫面換成俯視平面圖；畫筆圈選時換成可塗抹的畫布。
 */
import { ref, computed, watch } from 'vue'
import { Icon } from '@iconify/vue'
import LayoutEditor from '@/components/LayoutEditor.vue'
import RefineCanvas from '@/components/RefineCanvas.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

const {
  spacePhoto, spacePhotoPath, photoDetection, photoLayoutError, photoBusy, photoLayoutLoading,
  photoVersions, photoCurrent, photoStyleId, currentVersion, editableFurniture,
  editPlacements, roomW, roomD, roomTypeForPlan, extraPrompt,
  styleOptions, styleDemoImages,
  uploadPhoto, restylePhoto, renderPhotoLayout, editPhotoFurniture, editPhotoByMask, autoRelayoutPhoto, resetPhotoLayout,
} = useDesignFlow()

const TOOLS = [
  { key: 'upload',  icon: 'mdi:image-plus-outline', title: '上傳照片',       sub: '拍一張你現在的房間' },
  { key: 'style',   icon: 'mdi:palette-outline',    title: '修改風格',       sub: '家具位置不變，只換裝潢風格' },
  { key: 'layout',  icon: 'mdi:arrow-all',          title: '調整家具位置',   sub: '拖曳移動，或讓 AI 自動重排' },
  { key: 'replace', icon: 'mdi:swap-horizontal',    title: '置換或刪除家具', sub: '點選家具，或用畫筆圈出範圍' },
]
const hasPhoto = computed(() => !!spacePhotoPath.value && !!photoDetection.value)
const tool = ref(hasPhoto.value ? 'style' : 'upload')
const busy = computed(() => !!photoBusy.value || photoLayoutLoading.value)

function openTool(key) {
  if (key !== 'upload' && !hasPhoto.value) return
  tool.value = key
}
watch(hasPhoto, (ok) => { if (ok && tool.value === 'upload') tool.value = 'style' })

function onFile(e) {
  const f = e.target.files?.[0]
  if (!f) return
  spacePhoto.onChange(e)
  uploadPhoto(f)
  e.target.value = ''
}

function onPlacements(next) { editPlacements.value = next }

// ── 風格 ──
const styles = computed(() => styleOptions.value.filter(o => o.value !== 'auto'))

// ── 換／刪家具 ──
const selectedId = ref('')
const replacement = ref('')
const selected = computed(() => editableFurniture.value.find(f => f.id === selectedId.value) || null)
watch(editableFurniture, (list) => { if (!list.some(f => f.id === selectedId.value)) selectedId.value = '' })
// 'pick' 點偵測框；'brush' 自己塗。家具移過位置的版本框對不上，只能用畫筆
const pickMode = ref('pick')
watch(() => currentVersion.value?.aligned, (ok) => { if (ok === false) pickMode.value = 'brush' }, { immediate: true })
const brushMode = computed(() => tool.value === 'replace' && pickMode.value === 'brush')
const canvasRef = ref(null)
const drawMode = ref('draw')
const brushSize = ref(36)
const hasMask = computed(() => !!canvasRef.value?.hasMask)
const canSubmit = computed(() => (brushMode.value ? hasMask.value : !!selected.value))

async function doEdit(action) {
  if (!canSubmit.value || (action === 'replace' && !replacement.value.trim())) return
  if (brushMode.value) await editPhotoByMask(await canvasRef.value.getMaskBlob(), action, replacement.value)
  else await editPhotoFurniture(selected.value, action, replacement.value)
  if (!photoLayoutError.value) replacement.value = ''
}
const targetLabel = computed(() => (brushMode.value ? '塗抹的範圍' : selected.value?.label || ''))

// 照片上的偵測框：只在點選模式顯示，且目前這張圖的家具還在原位才對得上
const boxes = computed(() => (tool.value === 'replace' && !brushMode.value ? editableFurniture.value : []).map(f => {
  const [x0, y0, x1, y1] = f.box
  return { ...f, style: { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` } }
}))
</script>

<template>
  <div class="ps">
    <!-- ══ 左：目前的圖＋版本 ══ -->
    <section class="ps-stage">
      <div class="stage-box">
        <div v-if="tool === 'layout' && hasPhoto" class="stage-fill stage-editor">
          <LayoutEditor
            compact
            :placements="editPlacements"
            v-model:room-w="roomW"
            v-model:room-d="roomD"
            :room-type="roomTypeForPlan"
            @update:placements="onPlacements"
          />
        </div>
        <div v-else-if="brushMode && currentVersion" class="stage-fill">
          <RefineCanvas ref="canvasRef" fill :image-url="currentVersion.url" :brush-size="brushSize" :draw-mode="drawMode" />
        </div>
        <div v-else-if="currentVersion" class="stage-img">
          <img :src="currentVersion.url" :alt="currentVersion.label" />
          <button
            v-for="b in boxes" :key="b.id" type="button"
            class="fbox" :class="{ active: b.id === selectedId }" :style="b.style"
            :disabled="busy" @click="selectedId = b.id"
          ><span class="fbox-tag">{{ b.label }}</span></button>
        </div>
        <label v-else class="stage-empty">
          <input type="file" accept="image/*" hidden :disabled="busy" @change="onFile" />
          <Icon icon="mdi:camera-outline" width="44" />
          <strong>上傳你現在的房間照片</strong>
          <small>JPG、PNG、WebP，盡量拍到地板與整面牆</small>
        </label>

        <div v-if="busy" class="stage-busy" role="status">
          <div class="spinner"></div>
          <span>{{ photoBusy || 'AI 處理中…' }}</span>
          <small>約 10–60 秒</small>
        </div>
      </div>

      <p v-if="photoLayoutError" class="db-error stage-error">{{ photoLayoutError }}</p>

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

    <!-- ══ 右：四個功能 ══ -->
    <aside class="ps-tools">
      <section
        v-for="(t, n) in TOOLS" :key="t.key" class="tool"
        :class="{ open: tool === t.key, locked: t.key !== 'upload' && !hasPhoto }"
      >
        <button type="button" class="tool-head" :aria-expanded="tool === t.key" @click="openTool(t.key)">
          <span class="tool-num">{{ n + 1 }}</span>
          <Icon :icon="t.icon" width="22" class="tool-icon" />
          <span class="tool-text"><strong>{{ t.title }}</strong><small>{{ t.sub }}</small></span>
        </button>

        <div v-if="tool === t.key" class="tool-body">
          <!-- 1 上傳 -->
          <template v-if="t.key === 'upload'">
            <p v-if="hasPhoto" class="note">已偵測到 {{ photoDetection.furniture_placements.length }} 件家具，可以開始改造。</p>
            <label class="db-btn db-btn--sm file-btn" :class="{ disabled: busy }">
              <input type="file" accept="image/*" hidden :disabled="busy" @change="onFile" />
              {{ hasPhoto ? '換一張照片' : '選擇照片' }}
            </label>
          </template>

          <!-- 2 風格 -->
          <template v-else-if="t.key === 'style'">
            <div class="style-grid">
              <button
                v-for="s in styles" :key="s.value" type="button" class="style-card"
                :class="{ active: s.value === photoStyleId }" :disabled="busy" @click="restylePhoto(s.value)"
              >
                <img v-if="styleDemoImages[s.value]" :src="styleDemoImages[s.value]" :alt="s.name" />
                <span v-else class="style-empty"></span>
                <span class="style-name">{{ s.name }}</span>
              </button>
            </div>
            <input v-model="extraPrompt" class="db-input mini-input" placeholder="補充需求（選填），例如：木質感、明亮" />
          </template>

          <!-- 3 家具位置 -->
          <template v-else-if="t.key === 'layout'">
            <div class="row">
              <button type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="busy" @click="autoRelayoutPhoto">AI 自動重排</button>
              <button type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="busy" @click="resetPhotoLayout">還原</button>
              <button type="button" class="db-btn db-btn--sm grow" :disabled="busy || !editPlacements.length" @click="renderPhotoLayout">套用並生成</button>
            </div>
            <p class="note">在左邊的俯視圖拖曳家具；點一下家具可以旋轉或刪除。上方是遠處的牆，下方靠近鏡頭。</p>
            <img v-if="currentVersion" :src="currentVersion.url" alt="目前的照片" class="ref-photo" />
          </template>

          <!-- 4 換／刪家具 -->
          <template v-else>
            <div class="seg" role="tablist">
              <button
                type="button" role="tab" :class="{ active: pickMode === 'pick' }"
                :disabled="busy || !currentVersion?.aligned" @click="pickMode = 'pick'"
              >點選家具</button>
              <button type="button" role="tab" :class="{ active: pickMode === 'brush' }" :disabled="busy" @click="pickMode = 'brush'">畫筆圈選</button>
            </div>

            <template v-if="brushMode">
              <div class="row">
                <div class="seg seg--sm">
                  <button type="button" :class="{ active: drawMode === 'draw' }" @click="drawMode = 'draw'">
                    <Icon icon="mdi:brush" width="15" />畫筆
                  </button>
                  <button type="button" :class="{ active: drawMode === 'erase' }" @click="drawMode = 'erase'">
                    <Icon icon="mdi:eraser" width="15" />橡皮擦
                  </button>
                </div>
                <input v-model.number="brushSize" type="range" min="8" max="120" class="grow" aria-label="筆刷大小" />
                <button type="button" class="link-btn" :disabled="!hasMask" @click="canvasRef?.clearMask()">清除</button>
              </div>
              <p v-if="!hasMask" class="note">在左邊照片上把要換掉或刪除的家具塗紅。</p>
            </template>

            <template v-else>
              <p v-if="!currentVersion?.aligned" class="note warn">這一版的家具位置改過，請改用畫筆圈選。</p>
              <div class="chips">
                <button
                  v-for="f in editableFurniture" :key="f.id" type="button" class="chip"
                  :class="{ active: f.id === selectedId }" :disabled="busy" @click="selectedId = f.id"
                >{{ f.label }}</button>
              </div>
              <p v-if="!selected" class="note">點選左邊照片上的框，或上面的家具名稱。</p>
            </template>

            <template v-if="canSubmit">
              <div class="row">
                <input
                  v-model="replacement" class="db-input mini-input grow"
                  :placeholder="`把${targetLabel}換成…（例如：淺灰布沙發）`" @keyup.enter="doEdit('replace')"
                />
                <button type="button" class="db-btn db-btn--sm" :disabled="busy || !replacement.trim()" @click="doEdit('replace')">置換</button>
              </div>
              <button type="button" class="db-btn db-btn--ghost db-btn--sm danger" :disabled="busy" @click="doEdit('remove')">
                刪除{{ targetLabel }}
              </button>
            </template>
          </template>
        </div>
      </section>
    </aside>
  </div>
</template>

<style scoped>
/* 一個畫面內放完：高度扣掉導覽列、流程列、返回按鈕與卡片上下留白 */
.ps {
  --ps-h: max(380px, calc(100vh - 275px));
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(300px, 34vw, 440px);
  gap: 1.25rem;
  height: var(--ps-h);
  padding-bottom: 0.75rem;
}

.ps-stage { display: flex; flex-direction: column; gap: 0.6rem; min-height: 0; }
.stage-box {
  position: relative; flex: 1; min-height: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: 12px; background: #f4f2ee; overflow: hidden;
}
.stage-img { position: relative; max-width: 100%; max-height: 100%; line-height: 0; }
.stage-fill { position: absolute; inset: 0; }
/* 俯視圖吃滿左邊大畫面，扣掉工具列 */
.stage-editor { display: flex; flex-direction: column; padding: 0.6rem; background: #fff; border: 1px solid #ebe7e0; border-radius: 12px; }
.stage-editor :deep(.editor) { flex: 1; min-height: 0; }
.stage-editor :deep(.workspace) { flex: 1; min-height: 0; }
.stage-editor :deep(.board-viewport) { height: 100%; }
.stage-img img { display: block; max-width: 100%; max-height: calc(var(--ps-h) - 110px); object-fit: contain; }
.fbox {
  position: absolute; padding: 0; border: 2px solid #3b82f6; border-radius: 4px;
  background: rgba(59, 130, 246, 0.08); cursor: pointer;
}
.fbox:hover { background: rgba(59, 130, 246, 0.2); }
.fbox.active { border-color: #f59e0b; background: rgba(245, 158, 11, 0.22); }
.fbox-tag {
  position: absolute; top: -1px; left: -1px; padding: 2px 6px; border-radius: 4px 0 4px 0;
  background: #3b82f6; color: #fff; font-size: 0.72rem; line-height: 1.4; white-space: nowrap;
}
.fbox.active .fbox-tag { background: #f59e0b; }
.stage-empty {
  display: flex; flex-direction: column; align-items: center; gap: 0.5rem;
  color: var(--db-text-soft); cursor: pointer; text-align: center; padding: 2rem;
}
.stage-empty strong { color: var(--db-text); font-size: 1.1rem; }
.stage-busy {
  position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.5rem; background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(2px); color: var(--db-text);
}
.stage-busy small { color: var(--db-text-soft); }
.spinner {
  width: 34px; height: 34px; border-radius: 50%;
  border: 3px solid #e5e1d8; border-top-color: #756d66;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.stage-error { margin: 0; }

.versions { display: flex; gap: 0.5rem; overflow-x: auto; flex-shrink: 0; padding-bottom: 2px; }
.ver {
  flex: 0 0 auto; display: flex; flex-direction: column; gap: 2px; width: 92px; padding: 3px;
  border: 2px solid transparent; border-radius: 8px; background: #fff; cursor: pointer; text-align: left;
}
.ver img { width: 100%; height: 54px; object-fit: cover; border-radius: 5px; }
.ver span { font-size: 0.7rem; color: var(--db-text-soft); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ver.active { border-color: #756d66; }

.ps-tools { display: flex; flex-direction: column; gap: 0.5rem; min-height: 0; overflow-y: auto; }
.tool { flex-shrink: 0; border: 1px solid #ebe7e0; border-radius: 12px; background: #fff; }
.tool.open { flex-shrink: 1; min-height: 0; border-color: #756d66; display: flex; flex-direction: column; }
.tool.locked .tool-head { opacity: 0.45; cursor: not-allowed; }
.tool-head {
  display: flex; align-items: center; gap: 0.65rem; width: 100%; padding: 0.65rem 0.85rem;
  border: none; background: none; cursor: pointer; text-align: left; font: inherit; color: var(--db-text);
}
.tool-num {
  flex-shrink: 0; width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center;
  background: #f1eee8; font-size: 0.75rem; color: var(--db-text-soft);
}
.tool.open .tool-num { background: #756d66; color: #fff; }
.tool-icon { flex-shrink: 0; color: #756d66; }
.tool-text { display: flex; flex-direction: column; min-width: 0; }
.tool-text strong { font-size: 0.98rem; font-weight: 600; }
.tool-text small { font-size: 0.76rem; color: var(--db-text-soft); }
.tool-body {
  display: flex; flex-direction: column; gap: 0.6rem; padding: 0 0.85rem 0.85rem;
  min-height: 0; overflow-y: auto;
}

.note { margin: 0; font-size: 0.82rem; color: var(--db-text-soft); line-height: 1.6; }
.note.warn { color: #b45309; }
.row { display: flex; gap: 0.45rem; align-items: center; }
/* 側欄空間有限：按鈕比全站預設小一號 */
.tool-body .db-btn { min-width: 0; min-height: 34px; padding: 0.35rem 0.85rem; font-size: 0.88rem; white-space: nowrap; }
.grow { flex: 1; }
.mini-input { padding: 0.45rem 0.7rem; font-size: 0.85rem; }
.file-btn { align-self: flex-start; cursor: pointer; }
.file-btn.disabled { opacity: 0.5; pointer-events: none; }
.danger { color: #b91c1c; align-self: flex-start; }

.style-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.45rem; }
.style-card {
  display: flex; flex-direction: column; gap: 3px; padding: 3px; border: 2px solid transparent;
  border-radius: 8px; background: #faf9f6; cursor: pointer;
}
.style-card img, .style-empty { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 5px; background: #ece8e1; }
.style-name { font-size: 0.72rem; color: var(--db-text); text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.style-card.active { border-color: #756d66; }
.style-card:disabled { opacity: 0.6; cursor: default; }

.ref-photo { width: 100%; max-height: 160px; object-fit: contain; border-radius: 8px; background: #f4f2ee; }
.seg { display: flex; padding: 3px; border-radius: 999px; background: #f1eee8; }
.seg button {
  flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 0.25rem;
  padding: 0.35rem 0.7rem; border: none; border-radius: 999px; background: none;
  font: inherit; font-size: 0.85rem; color: var(--db-text-soft); cursor: pointer;
}
.seg button.active { background: #fff; color: var(--db-text); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12); }
.seg button:disabled { opacity: 0.45; cursor: not-allowed; }
.seg--sm { flex: 0 0 auto; }
.link-btn { border: none; background: none; font: inherit; font-size: 0.82rem; text-decoration: underline; cursor: pointer; color: var(--db-text-soft); }
.link-btn:disabled { opacity: 0.4; cursor: default; }

.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip {
  padding: 0.3rem 0.75rem; border: 1px solid #e2ddd4; border-radius: 999px; background: #fff;
  font: inherit; font-size: 0.82rem; cursor: pointer;
}
.chip.active { border-color: #f59e0b; background: #fff7e8; }

/* 矮螢幕：收起來的區塊只留標題，讓展開的那一塊有空間 */
@media (max-height: 760px) {
  .tool:not(.open) .tool-text small { display: none; }
  .tool-head { padding: 0.5rem 0.8rem; }
}
@media (max-width: 760px) {
  .ps { grid-template-columns: 1fr; height: auto; }
  .stage-box { min-height: 300px; }
  .stage-img img { max-height: 60vh; }
  .ps-tools { overflow: visible; }
}
</style>
