<script setup>
/**
 * Step 3D渲染圖 — Figma MacBook Air - 13（輸入）/ 15（結果）/ 18（環景）
 *
 * 與設計稿的差異：
 *  · 360° 環景不獨立成一步。它要跑 30–60 秒且不是每次都想看，所以沿用舊版做法，
 *    留在這一步、按了才生成，看完再往下走。
 *  · 風格推薦用既有的 StyleSuggestions（10 張、相似度標籤、ⓘ 資訊卡、下一輪／找相似），
 *    不是設計稿的三張靜態縮圖。
 *  · 裝潢風格下拉、風格參考圖上傳、不套用風格收進進階設定。
 */
import { ref, computed, defineAsyncComponent } from 'vue'
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import FengshuiPicker from '@/components/FengshuiPicker.vue'
import StyleSuggestions from '@/components/StyleSuggestions.vue'
import ImageUpload from '@/components/ImageUpload.vue'
import DesignDetails from '@/components/steps/DesignDetails.vue'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'
import { API_BASE } from '@/config/api'

// PanoramaViewer 吃 three.js（約 700KB）：只有真的要看環景時才下載，
// 不然連首頁都會被拖著一起載。
const PanoramaViewer = defineAsyncComponent(() => import('@/components/PanoramaViewer.vue'))

const {
  planSource, extraPrompt, outputAspect, fengshuiRules, roomTypeForPlan,
  selectedStyle, noStyleReference, styleRefImage,
  styleOptions, styleLoading, styleError, fetchStyleOptions,
  styleCandidates, candidatesLoading, confirmedStyle, showSuggestions,
  confirmStyle, clearConfirmedStyle, fetchStyleCandidates, showNextRound, scheduleSearch,
  result, loading, submit3D, nextStep, prevStep,
  swappingStyle, swapStyle, styleSwapCache, styleDemoImages,
  panoLoading, panoUrl, panoError, generatePanorama,
} = useDesignFlow()

const showPano = ref(false)
const showDetails = ref(false)

const imageUrl = computed(() => result.value?.generated_image_url || '')
const isSkipPath = computed(() => planSource.value === 'skip')
// 「自動」對換風格沒有意義（重送同一個 plan、style_profile_id=auto 只會重查一次語意搜尋，
// 不保證換成別的風格），一鍵換風格只列有固定 LoRA 對應的實際風格。
const swapStyleOptions = computed(() => styleOptions.value.filter(opt => opt.value !== 'auto'))
const activeStyleId = computed(() => result.value?.style_params?.style_profile_id)

/**
 * 整層房屋（cad）與上傳平面圖（upload）這兩條路徑沒有「空間設定」那一步，
 * 風水選單因此在前面的步驟裡沒有落腳處，只能擺在這裡。
 *
 * 其他路徑不重複顯示：它們在第一步就選過了，同一份狀態在兩頁各放一個控制項，
 * 只會讓人以為是兩組設定。
 */
const showFengshui = computed(
  () => planSource.value === 'cad' || planSource.value === 'upload',
)

// 排家具路徑在這一頁才打描述，打字時重查風格推薦（debounce 在 scheduleSearch 裡）
function onPromptInput() { scheduleSearch() }

// 不排家具路徑的描述在第一頁，「修改」就是退回去
function goEditPrompt() { prevStep() }

function regenerate() {
  showPano.value = false
  result.value = null
  styleSwapCache.value = {}   // 房間/描述可能都要重打了，舊風格版本的快取跟著失效
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

      <!-- ══ 風水禁忌（只有 cad／upload 路徑在這裡出現，見 showFengshui）══
           這兩條路徑的家具座標在「繪製平面圖」那一步就定下來了，所以這裡勾選只會
           進生成效果圖的描述，不會回頭搬動平面圖上的家具——hint 要把這件事講明白，
           不然使用者會以為勾了平面圖就會跟著改。 -->
      <FengshuiPicker
        v-if="showFengshui"
        v-model="fengshuiRules"
        :room-type="roomTypeForPlan"
        hint="勾選的項目會寫進生成效果圖的描述；這條路徑的平面圖家具位置已經定了，不會再被搬動。"
      />

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
      <div class="result-stage" :class="{ 'is-swapping': swappingStyle }">
        <img v-if="imageUrl" :src="imageUrl" alt="生成的 3D 渲染圖" class="result-img" />
        <p v-else class="no-img">生成完成，但沒有取得圖片 URL。</p>
      </div>

      <!-- 一鍵換風格：沿用同一個房間佈局／視角，只重換風格 LoRA 重繪。
           已經生成過的風格顯示實際成果縮圖、點了直接切換（不重打 API）；
           還沒生成的顯示風格庫的示範圖（styleDemoImages，見 style.js 的
           fetchStyleDemoImages），點了才送出換風格請求、生成後蓋掉示範圖。 -->
      <section class="style-swap">
        <h3 class="sub-title">一鍵換風格</h3>
        <div class="swap-row">
          <button
            v-for="opt in swapStyleOptions"
            :key="opt.value"
            type="button"
            class="swap-card"
            :class="{ active: opt.value === activeStyleId, generated: !!styleSwapCache[opt.value] }"
            :disabled="swappingStyle"
            :title="styleSwapCache[opt.value] ? `${opt.label}（已生成，點一下切換）` : `${opt.label}（點一下生成）`"
            @click="swapStyle(opt.value)"
          >
            <span class="swap-thumb">
              <img
                v-if="styleSwapCache[opt.value]?.generated_image_url || styleDemoImages[opt.value]"
                :src="styleSwapCache[opt.value]?.generated_image_url || styleDemoImages[opt.value]"
                :alt="opt.label"
              />
              <span v-else class="swap-thumb-empty">＋</span>
            </span>
            <span class="swap-label">{{ opt.label }}</span>
          </button>
        </div>
        <p v-if="swappingStyle" class="pano-hint">換風格中，沿用同一個房間佈局重新生成…</p>
      </section>

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
.result-stage.is-swapping .result-img { opacity: 0.5; transition: opacity 0.16s; }

.style-swap { margin-top: 0.5rem; }
.style-swap .sub-title { margin-bottom: 0.6rem; }
.swap-row { display: flex; flex-wrap: wrap; gap: 0.7rem; }
.swap-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  width: 84px;
  padding: 0;
  border: none;
  background: none;
  font-family: var(--db-font-body);
  cursor: pointer;
}
.swap-thumb {
  display: grid;
  place-items: center;
  width: 84px;
  height: 84px;
  border-radius: 12px;
  overflow: hidden;
  border: 2px solid #ececec;
  background: #f5f3ee;
  transition: border-color 0.16s, box-shadow 0.16s, transform 0.16s;
}
.swap-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.swap-thumb-empty { font-size: 1.4rem; color: var(--db-placeholder); }
.swap-card:hover:not(:disabled) .swap-thumb { border-color: var(--db-accent); }
.swap-card.generated .swap-thumb { border-style: solid; }
.swap-card.active .swap-thumb {
  border-color: var(--db-accent);
  box-shadow: 0 0 0 3px var(--db-accent-soft);
  transform: scale(1.03);
}
.swap-label {
  font-size: 0.8rem;
  color: var(--db-text-soft);
  text-align: center;
  line-height: 1.3;
}
.swap-card.active .swap-label { color: var(--db-text); font-weight: 600; }
.swap-card:disabled { opacity: 0.6; cursor: not-allowed; }

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
