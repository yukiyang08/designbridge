<script setup>
/**
 * Step 3D渲染圖 — Figma MacBook Air - 13（輸入）/ 15（結果）/ 18（環景）
 *
 * 與設計稿的差異：
 *  · 360° 環景不獨立成一步。它要跑 30–60 秒且不是每次都想看，所以沿用舊版做法，
 *    留在這一步、按了才生成，看完再往下走。
 *  · 風格推薦用既有的 StyleSuggestions（10 張、相似度標籤、ⓘ 資訊卡、下一輪／找相似），
 *    不是設計稿的三張靜態縮圖。
 *  · 裝潢風格下拉、風格參考圖上傳、不套用風格、styleMethod 收進進階設定。
 */
import { ref, computed, defineAsyncComponent } from 'vue'
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import StyleSuggestions from '@/components/StyleSuggestions.vue'
import ImageUpload from '@/components/ImageUpload.vue'
import DesignDetails from '@/components/steps/DesignDetails.vue'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'
import { API_BASE } from '@/config/api'

// PanoramaViewer 吃 three.js（約 700KB）：只有真的要看環景時才下載，
// 不然連首頁都會被拖著一起載。
const PanoramaViewer = defineAsyncComponent(() => import('@/components/PanoramaViewer.vue'))

const {
  planSource, extraPrompt, outputAspect,
  selectedStyle, noStyleReference, styleMethod, styleRefImage,
  styleOptions, styleLoading, styleError, fetchStyleOptions,
  styleCandidates, candidatesLoading, confirmedStyle, showSuggestions,
  confirmStyle, clearConfirmedStyle, fetchStyleCandidates, showNextRound, scheduleSearch,
  result, loading, submit3D, nextStep, prevStep,
  panoLoading, panoUrl, panoError, generatePanorama,
} = useDesignFlow()

const showPano = ref(false)
const showDetails = ref(false)

const imageUrl = computed(() => result.value?.generated_image_url || '')
const isSkipPath = computed(() => planSource.value === 'skip')

// 排家具路徑在這一頁才打描述，打字時重查風格推薦（debounce 在 scheduleSearch 裡）
function onPromptInput() { scheduleSearch() }

// 不排家具路徑的描述在第一頁，「修改」就是退回去
function goEditPrompt() { prevStep() }

function regenerate() {
  showPano.value = false
  result.value = null
  scheduleSearch()
}

function onPanoClick() {
  if (panoUrl.value) showPano.value = !showPano.value
  else generatePanorama().then(() => { showPano.value = !!panoUrl.value })
}
</script>

<template>
  <div class="render-step">

    <!-- ══ 尚未生成：描述 + 風格推薦 ══ -->
    <template v-if="!result">
      <!-- 不排家具路徑在第一頁就填過描述了（那是它唯一的設定頁），這裡只回顧，
           不再放一個綁同一個欄位的輸入框，免得同一件事被問兩次。
           排家具路徑的第一頁專心決定房型／家具／坪數，描述在這裡才填。 -->
      <div v-if="isSkipPath" class="recap">
        <span class="recap-label">你的描述</span>
        <p v-if="extraPrompt.trim()" class="recap-text">{{ extraPrompt }}</p>
        <p v-else class="recap-text is-empty">（未填寫，將只依風格參考生成）</p>
        <button type="button" class="recap-edit" @click="goEditPrompt">修改</button>
      </div>

      <template v-else>
        <h2 class="lead">描述你理想中的空間…</h2>
        <textarea
          v-model="extraPrompt"
          class="db-textarea prompt"
          rows="3"
          placeholder="輸入…例如：木質感、採光充足的明亮感"
          @input="onPromptInput"
        />
      </template>

      <!-- StyleSuggestions 自己有「AI 推薦風格參考」標題，這裡不再重複一層 -->
      <section v-if="showSuggestions" class="suggest">
        <StyleSuggestions
          :candidates="styleCandidates"
          :confirmed="confirmedStyle"
          :loading="candidatesLoading"
          :api-base="API_BASE"
          @confirm="confirmStyle"
          @clear="clearConfirmedStyle"
          @search="confirmedStyle ? fetchStyleCandidates({ anchorSelected: true }) : showNextRound()"
        />
      </section>

      <AdvancedPanel hint="指定風格・參考圖・風格轉移方式・輸出比例">
        <div class="adv-grid">
          <div class="adv-field">
            <label class="field-label" for="style-select">裝潢風格</label>
            <select id="style-select" v-model="selectedStyle" class="db-input" :disabled="styleLoading">
              <option v-for="opt in styleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <p v-if="styleLoading" class="field-hint">載入中…</p>
            <p v-if="styleError" class="field-hint error">
              {{ styleError }}
              <button type="button" class="retry" @click="fetchStyleOptions">重試</button>
            </p>
          </div>

          <div class="adv-field">
            <label class="field-label" for="aspect-r">輸出圖片長寬比</label>
            <select id="aspect-r" v-model="outputAspect" class="db-input">
              <option v-for="opt in ASPECT_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <div class="adv-field adv-span">
            <div class="label-row">
              <label class="field-label">風格參考圖</label>
              <label class="toggle">
                <input type="checkbox" v-model="noStyleReference" />
                <span>不套用風格</span>
              </label>
            </div>
            <template v-if="!noStyleReference">
              <ImageUpload
                label="點擊或拖曳上傳"
                icon="🖼️"
                hint="上傳想要的風格圖片，AI 會參考其色調與氛圍"
                :preview="styleRefImage.preview"
                @change="styleRefImage.onChange"
                @remove="styleRefImage.remove"
              />
              <div v-if="styleRefImage.preview" class="method-group">
                <label v-for="m in [
                  { v: 'ai_analysis', t: 'AI 分析風格', s: 'Gemini 解析色調，注入 prompt' },
                  { v: 'redux',       t: 'FLUX.1-Redux', s: '以圖為主做風格遷移' },
                  { v: 'ipadapter',   t: 'IP-Adapter',  s: '圖像注入風格' },
                ]" :key="m.v" :class="['method', { active: styleMethod === m.v }]">
                  <input type="radio" v-model="styleMethod" :value="m.v" />
                  <span class="method-body">
                    <strong>{{ m.t }}</strong>
                    <small>{{ m.s }}</small>
                  </span>
                </label>
              </div>
            </template>
          </div>
        </div>
      </AdvancedPanel>

      <div class="actions">
        <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 上一步</button>
        <button class="db-btn" :disabled="loading" @click="submit3D">生成渲染圖</button>
      </div>
    </template>

    <!-- ══ 已生成：結果 + 360° 環景 ══ -->
    <template v-else>
      <div class="result-stage">
        <img v-if="imageUrl" :src="imageUrl" alt="生成的 3D 渲染圖" class="result-img" />
        <p v-else class="no-img">生成完成，但沒有取得圖片 URL。</p>
      </div>

      <!-- 360° 環景：設計稿是獨立步驟，這裡改回同頁按需生成 -->
      <section class="pano">
        <div class="pano-head">
          <h3 class="sub-title">360° 環景</h3>
          <button
            class="db-btn db-btn--sm"
            :disabled="panoLoading || !result.task_id"
            @click="onPanoClick"
          >
            <span v-if="panoLoading">生成中，約 30–60 秒…</span>
            <span v-else-if="panoUrl">{{ showPano ? '收合環景' : '查看 360° 環景' }}</span>
            <span v-else>生成 360° 環景</span>
          </button>
        </div>
        <p v-if="panoError" class="db-error">⚠ {{ panoError }}</p>
        <p v-else-if="!panoUrl && !panoLoading" class="pano-hint">
          以這張渲染圖生成可拖曳環顧的全景圖，需要額外運算時間，按了才會跑。
        </p>
        <PanoramaViewer v-if="panoUrl && showPano" :image-url="panoUrl" />
      </section>

      <!-- 設計詳情（結構化需求 / 風格參數 / 點雲 / raw JSON） -->
      <div class="details-toggle-wrap">
        <button type="button" class="details-toggle" @click="showDetails = !showDetails">
          {{ showDetails ? '▾' : '▸' }} 設計詳情
        </button>
      </div>
      <DesignDetails v-if="showDetails" :result="result" />

      <div class="actions">
        <button class="db-btn db-btn--ghost db-btn--sm" @click="regenerate">重新調整並生成</button>
        <button class="db-btn" @click="nextStep">下一步：微調編輯</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.render-step { display: flex; flex-direction: column; }

.lead {
  margin: 0 0 0.9rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.5rem;
  color: var(--db-text);
}
.prompt { max-width: 720px; }

.recap {
  display: flex;
  align-items: baseline;
  gap: 0.85rem;
  padding: 0.9rem 1.1rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.recap-label {
  flex-shrink: 0;
  font-size: 0.8rem;
  color: var(--db-text-soft);
}
.recap-text {
  flex: 1;
  margin: 0;
  min-width: 0;
  font-size: 0.95rem;
  line-height: 1.7;
  color: var(--db-text);
  overflow-wrap: anywhere;
}
.recap-text.is-empty { color: var(--db-placeholder); }
.recap-edit {
  flex-shrink: 0;
  border: none;
  background: none;
  color: var(--db-accent-deep);
  font-size: 0.85rem;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.recap-edit:hover { color: var(--db-text); }

.sub-title {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.25rem;
  color: var(--db-text);
}

.suggest { margin-top: 1.75rem; }
.suggest .sub-title { margin-bottom: 0.75rem; }

.adv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 1.25rem 1.5rem;
}
.adv-span { grid-column: 1 / -1; }
.field-label {
  display: block;
  margin-bottom: 0.45rem;
  font-size: 0.88rem;
  font-weight: 500;
  color: var(--db-text-soft);
}
.field-hint { margin: 0.4rem 0 0; font-size: 0.78rem; color: var(--db-placeholder); }
.field-hint.error { color: var(--db-danger); }
.retry {
  margin-left: 0.5rem;
  border: none;
  background: none;
  color: var(--db-accent-deep);
  text-decoration: underline;
  cursor: pointer;
  font-size: 0.78rem;
}

.label-row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.82rem;
  color: var(--db-text-soft);
  cursor: pointer;
}

.method-group { display: grid; gap: 0.5rem; margin-top: 0.75rem; }
.method {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  padding: 0.6rem 0.8rem;
  border: 2px solid #ececec;
  border-radius: var(--db-radius-chip);
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s;
}
.method.active { border-color: var(--db-accent); background: #fbfaf6; }
.method-body { display: flex; flex-direction: column; }
.method-body strong { font-size: 0.9rem; font-weight: 600; }
.method-body small { color: var(--db-text-soft); font-size: 0.78rem; }

/* 結果 */
.result-stage {
  display: grid;
  place-items: center;
  padding: 0.5rem 0 1.25rem;
}
.result-img {
  max-width: 100%;
  max-height: 60vh;
  border-radius: 8px;
  box-shadow: var(--db-shadow-soft);
}
.no-img { color: var(--db-text-soft); }

.pano { margin-top: 0.75rem; }
.pano-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.75rem;
}
.pano-head .db-btn { margin-left: auto; }
.pano-hint { margin: 0; color: var(--db-text-soft); font-size: 0.86rem; }

.details-toggle-wrap { margin-top: 1.5rem; }
.details-toggle {
  border: none;
  background: none;
  padding: 0;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 0.92rem;
  cursor: pointer;
}
.details-toggle:hover { color: var(--db-text); }

.actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding-top: 1.75rem;
}

@media (max-width: 900px) {
  .actions { flex-direction: column-reverse; }
  .actions .db-btn { width: 100%; }
  .pano-head .db-btn { margin-left: 0; width: 100%; }
}
</style>
