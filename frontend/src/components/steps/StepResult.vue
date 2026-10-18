<script setup>
/**
 * Step 生成結果（render ＋ refine ＋ budget 三個舊 step 合併）
 *
 * 原本是三個獨立步驟：3D渲染圖 → 微調編輯 → 預算估計。三者其實都只是圍著同一張
 * 生成圖打轉——StepRender 本來就用 v-if="!result" 在一頁內切換「設定表單／結果」
 * 兩態，submitRefine／fetchQuotation 也都是原地更新 result、不跳頁——所以合併成
 * 一頁並不需要改資料流，只是把三段 UI 疊在同一個 template 裡，由上到下：
 *   1. 結果圖＋一鍵換風格＋360°環景＋設計詳情
 *   2. 微調：需求輸入＋畫筆/橡皮擦工具＋畫布
 *   3. 家具預算：候選清單＋總價
 * 「開始新的設計」「收藏這個設計」固定在頁尾最下面。
 *
 * 還沒生成時（!result）沿用原 StepRender 的設定表單（描述/風格推薦/風水/進階設定）。
 */
import { ref, reactive, computed, watch, defineAsyncComponent } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import FengshuiPicker from '@/components/FengshuiPicker.vue'
import StyleSuggestions from '@/components/StyleSuggestions.vue'
import ImageUpload from '@/components/ImageUpload.vue'
import DesignDetails from '@/components/steps/DesignDetails.vue'
import ApplyToRooms from '@/components/steps/ApplyToRooms.vue'
import RefineCanvas from '@/components/RefineCanvas.vue'
import TimingPanel from '@/components/TimingPanel.vue'
import { useDesignFlow, ASPECT_OPTIONS, ORIGINAL_STYLE_KEY } from '@/composables/useDesignFlow'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import { API_BASE } from '@/config/api'

// PanoramaViewer 吃 three.js（約 700KB）：只有真的要看環景時才下載。
const PanoramaViewer = defineAsyncComponent(() => import('@/components/PanoramaViewer.vue'))

const {
  planSource, extraPrompt, outputAspect, fengshuiRules, roomTypeForPlan,
  selectedStyle, noStyleReference, styleRefImage,
  styleOptions, styleLoading, styleError, fetchStyleOptions,
  styleCandidates, candidatesLoading, candidatesError, confirmedStyle, showSuggestions,
  confirmStyle, clearConfirmedStyle, fetchStyleCandidates, showNextRound, scheduleSearch,
  result, loading, submit3D, prevStep,
  swappingStyle, swapStyle, restoreOriginal, styleSwapCache, styleDemoImages,
  panoLoading, panoUrl, panoError, generatePanorama,
  // 微調
  brushSize, eraserSize, drawMode, baseImagePreview, refineCanvasRef,
  textPrompt, submitRefine, undoRefine, canUndoRefine,
  // 預算
  quotationLoading, quotationError, fetchQuotation, resetFlow,
  favoriteLoading, favoriteError, toggleFavoriteDesign,
  // 整層多房間：引導設計下一間
  cadPlanResult, cadActiveRoomId, cadRoomStatus, handleCadRoomSelected,
} = useDesignFlow()
const {
  selectedCount: furnitureSelectedCount,
  toggle: toggleFavorite,
  isSelected: isFavorited,
} = useFurnitureSelection()

const router = useRouter()

const viewMode = ref('image')   // 'image' | 'pano'
const showDetails = ref(false)
const showTimings = ref(false)
const showRefine = ref(false)   // 微調工作區預設收起，按「開始微調」才跳出
function openRefine() { viewMode.value = 'image'; showRefine.value = true }

const imageUrl = computed(() => result.value?.generated_image_url || '')
const isSkipPath = computed(() => planSource.value === 'skip')
// 「自動」對換風格沒有意義（重送同一個 plan、style_profile_id=auto 只會重查一次語意搜尋，
// 不保證換成別的風格），一鍵換風格只列有固定 LoRA 對應的實際風格。
const swapStyleOptions = computed(() => styleOptions.value.filter(opt => opt.value !== 'auto'))
const activeStyleId = computed(() => result.value?.style_params?.style_profile_id)
// 原圖卡是不是目前正顯示的那張：直接比物件參照，restoreOriginal/submit3D 都是把
// result 設成 styleSwapCache 裡存的同一個物件，參照相等就代表現在看的就是它。
const isOriginalActive = computed(() => !!result.value && result.value === styleSwapCache.value[ORIGINAL_STYLE_KEY])

/**
 * 整層房屋（cad）與上傳平面圖（upload）這兩條路徑沒有「空間設定」那一步，
 * 風水選單因此在前面的步驟裡沒有落腳處，只能擺在這裡。
 */
const showFengshui = computed(
  () => planSource.value === 'cad' || planSource.value === 'upload',
)

/**
 * 整層多房間（cad）：結果頁捲到最下面才看得到「設計下一間」，不用再往上找
 * CadRoomMiniMap 那個側欄縮圖——那是被動的，螢幕窄於 1100px 時還會跑到內容
 * 上面，捲到頁尾時使用者很可能已經看不到它了。
 */
const cadTotalCount = computed(() => cadPlanResult.value?.rooms?.length || 0)
const cadDoneCount = computed(
  () => Object.values(cadRoomStatus.value).filter(s => s === 'done').length,
)
const cadAllDone = computed(() => cadTotalCount.value > 0 && cadDoneCount.value >= cadTotalCount.value)
const cadNextRoom = computed(() => {
  if (planSource.value !== 'cad' || !cadPlanResult.value) return null
  return (cadPlanResult.value.rooms || []).find(
    (r) => r.id !== cadActiveRoomId.value && cadRoomStatus.value[r.id] !== 'done',
  ) || null
})
function goNextRoom() {
  if (cadNextRoom.value) handleCadRoomSelected(cadNextRoom.value)
}

// 排家具路徑在這一頁才打描述，打字時重查風格推薦（debounce 在 scheduleSearch 裡）
function onPromptInput() { scheduleSearch() }

// 不排家具路徑的描述在第一頁，「修改」就是退回去
function goEditPrompt() { prevStep() }

function regenerate() {
  viewMode.value = 'image'
  result.value = null
  styleSwapCache.value = {}   // 房間/描述可能都要重打了，舊風格版本的快取跟著失效
  scheduleSearch()
}

// 沒有環景時 viewMode 即使是 'pano' 也顯示單圖（例如切到另一間房）
const showingPano = computed(() => viewMode.value === 'pano' && !!panoUrl.value)
async function startPano() {
  await generatePanorama()
  if (panoUrl.value) viewMode.value = 'pano'   // 生成完直接帶使用者過去
}
// 換了一張圖（換房間、重新生成）就回到單圖
watch(() => result.value?.task_id, () => { viewMode.value = 'image' })

// ── 微調 ──────────────────────────────────────────────────
// RefineCanvas 只吃一個 brush-size：畫筆模式用 brushSize，橡皮擦模式用 eraserSize
const activeBrushSize = computed(() => drawMode.value === 'erase' ? eraserSize.value : brushSize.value)

// ── 家具預算 ──────────────────────────────────────────────
const quotation = computed(() => result.value?.quotation_result || null)

// 生成結果一出來（或換風格／微調換了新圖）就自動估價——這三個動作都會把
// result 換成新物件、quotation_result 清掉（見 render.js/refine.js），watch 在這裡
// 補上原本「進到這一步就自動估價」的行為，只是觸發點從「掛載這個 step」換成
// 「result 換了一個沒有報價的新物件」，因為現在已經不會因為換頁而重新掛載。
watch(result, (r) => {
  if (r && !r.quotation_result && !quotationLoading.value) fetchQuotation()
}, { immediate: true })

const confirmingReset = ref(false)
function startOver() {
  resetFlow()
  router.push('/start')
}

// 每件家具目前選中的候選 index
const selectedCandidates = reactive({})
watch(
  () => quotation.value?.furniture_list,
  (list) => { if (list) list.forEach((_, idx) => { selectedCandidates[idx] = 0 }) },
  { immediate: true },
)

const computedTotal = computed(() => {
  const list = quotation.value?.furniture_list
  if (!list) return 0
  return list.reduce((sum, item, idx) => {
    const c = item.candidates?.[selectedCandidates[idx] ?? 0]
    return sum + (c?.price ?? 0)
  }, 0)
})

function toFavoriteItem(item, c) {
  return {
    id: c.id || c.purchase_url || `${item.detected_name}__${c.name}`,
    name: c.name,
    category: item.category,
    price: c.price,
    currency: 'TWD',
    url: c.purchase_url,
    image_url: c.product_image_url,
  }
}
</script>

<template>
  <div class="result-step">

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
          :error="candidatesError"
          :api-base="API_BASE"
          @confirm="confirmStyle"
          @clear="clearConfirmedStyle"
          @next-round="showNextRound"
          @retry="fetchStyleCandidates()"
          @similar="fetchStyleCandidates({ anchorSelected: true })"
        />
      </section>

      <!-- ══ 風水禁忌（只有 cad／upload 路徑在這裡出現，見 showFengshui）══ -->
      <FengshuiPicker
        v-if="showFengshui"
        v-model="fengshuiRules"
        :room-type="roomTypeForPlan"
      />

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

    <!-- ══ 已生成：結果圖 + 微調 + 預算，整頁往下排 ══ -->
    <template v-else>

      <!-- ── ① 結果圖 + 360° 環景 + 一鍵換風格 ── -->
      <section class="block block-image">
        <!-- 單圖／360° 分頁：有環景（或正在生成）才出現 -->
        <div v-if="panoUrl || panoLoading" class="view-tabs" role="tablist" aria-label="檢視模式">
          <button type="button" role="tab" :aria-selected="!showingPano" :class="{ active: !showingPano }" @click="viewMode = 'image'">單圖</button>
          <button
            type="button" role="tab" :aria-selected="showingPano" :class="{ active: showingPano }"
            :disabled="!panoUrl" @click="viewMode = 'pano'"
          >360° 環景<span v-if="panoLoading" class="tab-note">生成中…</span></button>
        </div>

        <div class="stage-row">
        <!-- 微調欄：放在結果圖左側，預設只有一顆按鈕，展開後右側的圖換成可塗抹的畫布 -->
        <aside class="refine-side" :class="{ open: showRefine }">
          <template v-if="!showRefine">
            <h2 class="block-title">微調編輯</h2>
            <p class="block-hint">對這張圖不滿意？用畫筆圈出想調整的範圍，AI 只重繪該區域。</p>
            <button type="button" class="db-btn refine-cta-btn" @click="openRefine">開始微調</button>
          </template>

          <template v-else>
            <div class="block-head">
              <h2 class="block-title">微調編輯</h2>
              <button type="button" class="collapse-link" @click="showRefine = false">收合</button>
            </div>
            <label class="field-label" for="refine-prompt">輸入你的微調需求</label>
            <textarea
              id="refine-prompt"
              v-model="textPrompt"
              class="db-textarea"
              rows="4"
              placeholder="例如：把沙發換成藍色布藝款式、窗簾改為白色薄紗"
            />

            <h3 class="tool-title">用畫筆圈選微調範圍</h3>

            <div class="tool-row">
              <button
                type="button"
                :class="['tool-btn', { active: drawMode === 'draw' }]"
                @click="drawMode = 'draw'"
              >畫筆</button>
              <input
                v-model.number="brushSize"
                type="range" min="5" max="120" step="5"
                class="slider" aria-label="筆刷大小"
              />
              <span class="slider-val">{{ brushSize }}px</span>
            </div>

            <div class="tool-row">
              <button
                type="button"
                :class="['tool-btn', { active: drawMode === 'erase' }]"
                @click="drawMode = 'erase'"
              >橡皮擦</button>
              <input
                v-model.number="eraserSize"
                type="range" min="5" max="120" step="5"
                class="slider" aria-label="橡皮擦大小"
              />
              <span class="slider-val">{{ eraserSize }}px</span>
            </div>

            <p class="tool-hint">
              不塗抹就整張重繪；塗抹後只重繪塗到的區域。
            </p>

            <div class="side-actions">
              <button class="db-btn" :disabled="loading" @click="submitRefine">
                生成新圖
              </button>
              <button
                v-if="canUndoRefine" class="db-btn db-btn--ghost db-btn--sm"
                title="回到微調前的圖片" @click="undoRefine"
              >↶ 還原上一版</button>
            </div>
          </template>
        </aside>

        <div v-if="showRefine" class="canvas-wrap">
          <RefineCanvas
            ref="refineCanvasRef"
            :image-url="baseImagePreview"
            :brush-size="activeBrushSize"
            :draw-mode="drawMode"
          />
        </div>
        <div v-else class="result-stage" :class="{ 'is-swapping': swappingStyle }">
          <PanoramaViewer v-if="showingPano" :image-url="panoUrl" class="stage-pano" />
          <div v-else class="stage-img-wrap">
            <img v-if="imageUrl" :src="imageUrl" alt="生成的 3D 渲染圖" class="result-img" />
            <p v-else class="no-img">生成完成，但沒有取得圖片 URL。</p>

            <!-- 滑鼠移到圖上才出現（觸控裝置沒有 hover，常駐顯示） -->
            <button
              v-if="imageUrl && result.task_id && !panoUrl && !panoLoading"
              type="button" class="pano-cta" :disabled="swappingStyle" @click="startPano"
            >
              <span class="cta-title">360° 環景模式</span>
              <span class="cta-sub">AI 依這張圖推測周圍空間，約 30–60 秒</span>
            </button>

            <div v-if="panoLoading" class="pano-overlay" role="status">
              <div class="pano-spinner"></div>
              <p>正在生成 360° 環景…約 30–60 秒</p>
            </div>

            <!-- 右下角：查看這次請求各環節耗時 -->
            <button
              v-if="imageUrl && result.timings?.length"
              type="button" class="timing-btn" title="各環節耗時" aria-label="查看各環節耗時"
              @click="showTimings = true"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
              </svg>
            </button>

            <div v-if="panoError && !panoLoading" class="pano-fail" role="alert">
              <span>⚠ {{ panoError }}</span>
              <button type="button" class="pano-retry" @click="startPano">重試</button>
            </div>
          </div>
        </div>
        </div>

        <!-- 一鍵換風格：沿用同一個房間佈局／視角，只重換風格 LoRA 重繪。 -->
        <section class="style-swap">
          <h3 class="sub-title">一鍵換風格</h3>
          <div class="swap-row">
            <button
              v-if="styleSwapCache[ORIGINAL_STYLE_KEY]"
              type="button"
              class="swap-card"
              :class="{ active: isOriginalActive, generated: true }"
              :disabled="swappingStyle"
              title="回到最一開始生成的那張"
              @click="restoreOriginal"
            >
              <span class="swap-thumb">
                <img :src="styleSwapCache[ORIGINAL_STYLE_KEY].generated_image_url" alt="原圖">
              </span>
              <span class="swap-label">原圖</span>
            </button>
            <button
              v-for="opt in swapStyleOptions"
              :key="opt.value"
              type="button"
              class="swap-card"
              :class="{ active: opt.value === activeStyleId, generated: !!styleSwapCache[opt.value] }"
              :disabled="swappingStyle"
              :title="styleSwapCache[opt.value] ? `${opt.name}，已生成，點一下切換` : `${opt.name}，點一下生成`"
              @click="swapStyle(opt.value)"
            >
              <span class="swap-thumb">
                <img
                  v-if="styleSwapCache[opt.value]?.generated_image_url || styleDemoImages[opt.value]"
                  :src="styleSwapCache[opt.value]?.generated_image_url || styleDemoImages[opt.value]"
                  :alt="opt.name"
                />
                <span v-else class="swap-thumb-empty">＋</span>
              </span>
              <span class="swap-label">{{ opt.name }}</span>
            </button>
          </div>
          <p v-if="swappingStyle" class="pano-hint">換風格中，沿用同一個房間佈局重新生成…</p>
        </section>

        <!-- 整層流程：把這間的設定套用到其他房間，一次生成 -->
        <ApplyToRooms />

        <!-- 設計詳情（結構化需求 / 風格參數 / 點雲 / raw JSON） -->
        <div class="details-toggle-wrap">
          <button type="button" class="details-toggle" @click="showDetails = !showDetails">
            {{ showDetails ? '▾' : '▸' }} 設計詳情
          </button>
        </div>
        <DesignDetails v-if="showDetails" :result="result" />
        <TimingPanel
          v-if="showTimings && result.timings?.length"
          :timings="result.timings" :elapsed="result.elapsed_time" :routing="result.routing_decision"
          @close="showTimings = false"
        />

        <div class="inline-actions">
          <button class="db-btn db-btn--ghost db-btn--sm" @click="regenerate">重新調整並生成</button>
        </div>
      </section>

      <!-- ── ③ 家具預算 ── -->
      <section class="block block-budget">
        <div class="head">
          <h2 class="block-title">
            根據設計方案，進行家具推薦
            <span class="badge">IKEA 台灣</span>
          </h2>
          <div class="head-actions">
            <RouterLink to="/furniture" class="link">
              前往家具查詢
              <span v-if="furnitureSelectedCount" class="count">{{ furnitureSelectedCount }}</span>
            </RouterLink>
            <button class="db-btn db-btn--sm" :disabled="quotationLoading" @click="fetchQuotation">
              {{ quotationLoading ? '估價中…' : (quotation ? '重新估價' : '取得家具報價') }}
            </button>
          </div>
        </div>

        <p v-if="quotationError" class="db-error">{{ quotationError }}</p>

        <template v-if="quotation">
          <div v-for="(item, idx) in quotation.furniture_list" :key="idx" class="row">
            <div class="row-label">{{ item.detected_name }}</div>
            <div class="candidates">
              <button
                v-for="(c, ci) in item.candidates"
                :key="ci"
                type="button"
                :class="['candidate', { selected: (selectedCandidates[idx] ?? 0) === ci }]"
                @click="selectedCandidates[idx] = ci"
              >
                <span class="img-wrap">
                  <img v-if="c.product_image_url" :src="c.product_image_url" :alt="c.name" />
                  <span v-else class="img-placeholder">資料庫沒有該項商品</span>
                </span>
                <span class="name">{{ c.name }}</span>
                <span class="price">NT$ {{ c.price.toLocaleString() }}</span>
                <span v-if="c.similarity > 0" class="sim">相似度 {{ (c.similarity * 100).toFixed(0) }}%</span>
                <span class="card-actions">
                  <a
                    v-if="c.purchase_url" :href="c.purchase_url"
                    target="_blank" rel="noopener" class="buy" @click.stop
                  >商品詳情</a>
                  <span
                    class="fav"
                    :class="{ active: isFavorited(toFavoriteItem(item, c)) }"
                    :title="isFavorited(toFavoriteItem(item, c)) ? '取消收藏' : '加入收藏'"
                    @click.stop="toggleFavorite(toFavoriteItem(item, c))"
                  >{{ isFavorited(toFavoriteItem(item, c)) ? '★' : '☆' }}</span>
                </span>
              </button>
            </div>
          </div>

          <div class="total">
            <span class="total-label">目前選擇預算</span>
            <span class="total-val">NT$ {{ computedTotal.toLocaleString() }}</span>
          </div>

          <p class="note">
            * 點選卡片可切換商品，總預算自動更新。{{ quotation.kb_match_count }}/{{ quotation.furniture_list.length }}
            件成功向量比對 IKEA，其餘為 AI 估算。
          </p>
        </template>

        <p v-else-if="quotationLoading" class="hint" role="status">
          正在辨識畫面中的家具並比對 IKEA 商品…約需 30 秒
        </p>
        <p v-else class="hint">
          尚未取得報價，點右上角「取得家具報價」重試。
        </p>
      </section>

      <!-- ── 整層多房間：引導設計下一間，不用再往上找側欄縮圖 ── -->
      <section v-if="planSource === 'cad' && cadPlanResult" class="next-room">
        <template v-if="cadNextRoom">
          <div class="next-room-row">
            <p class="next-room-progress">整層進度 {{ cadDoneCount }} / {{ cadTotalCount }} 間完成</p>
            <button type="button" class="db-btn next-room-btn" @click="goNextRoom">
              設計下一間：{{ cadNextRoom.label_zh }} →
            </button>
          </div>
          <p class="next-room-hint">也可以點擊右邊的平面圖，選其他空間當下一個設計目標</p>
        </template>
        <p v-else-if="cadAllDone" class="next-room-done">🎉 整層 {{ cadTotalCount }} 間房間都完成了！</p>
      </section>

      <!-- ── 頁尾：收藏 / 開始新的設計 / 上一步 ── -->
      <div v-if="result?.task_id" class="collect-row">
        <button
          type="button"
          :class="['collect-btn', { active: result.favorited }]"
          :disabled="favoriteLoading"
          @click="toggleFavoriteDesign()"
        >
          <span class="collect-star">{{ result.favorited ? '★' : '☆' }}</span>
          {{ result.favorited ? '已收藏這個設計' : '收藏這個設計' }}
        </button>
        <RouterLink to="/favorites" class="collect-link">在收藏設計查看 →</RouterLink>
        <p v-if="favoriteError" class="db-error collect-error">{{ favoriteError }}</p>
      </div>

      <div class="actions">
        <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 上一步</button>
        <template v-if="confirmingReset">
          <span class="reset-warn">目前的設計與報價會被清除</span>
          <button class="db-btn db-btn--ghost db-btn--sm" @click="confirmingReset = false">取消</button>
          <button class="db-btn db-btn--sm" @click="startOver">確定，重新開始</button>
        </template>
        <button v-else class="db-btn db-btn--ghost db-btn--sm" @click="confirmingReset = true">開始新的設計</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.result-step { display: flex; flex-direction: column; }

.block { display: flex; flex-direction: column; }
.block-budget {
  margin-top: 2rem;
  padding-top: 1.75rem;
  border-top: 1px solid #ececec;
}
.block-title {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.3rem;
  color: var(--db-text);
}

/* 微調欄：結果圖左側 */
.stage-row {
  display: grid;
  grid-template-columns: minmax(240px, 300px) 1fr;
  gap: clamp(1rem, 2.5vw, 2rem);
  align-items: start;
  padding: 0.5rem 0 1.25rem;
}
.stage-row > .result-stage { padding: 0; min-width: 0; }
.refine-side {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.1rem 1.25rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-accent-soft);
}
.refine-side.open { background: none; padding: 0; gap: 0; }
.refine-cta-btn { align-self: flex-start; padding: 0.7rem 1.5rem; font-size: 1rem; }
.side-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; margin-top: 1.25rem; }
.block-hint { margin: 0; color: var(--db-text-soft); font-size: 0.9rem; line-height: 1.6; }

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
.collapse-link {
  flex-shrink: 0;
  border: none;
  background: none;
  padding: 0;
  color: var(--db-accent-deep);
  font-size: 0.85rem;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.collapse-link:hover { color: var(--db-text); }

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

/* 單圖／360° 分頁 */
.view-tabs {
  display: inline-flex;
  align-self: center;
  padding: 3px;
  margin-top: 0.5rem;
  border: 1px solid #e2ddd0;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
}
.view-tabs button {
  padding: 0.4rem 1.1rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.view-tabs button:not(.active):not(:disabled):hover { background: rgba(255, 255, 255, 0.7); color: var(--db-text); }
.view-tabs button.active { background: var(--db-accent); color: var(--db-on-accent); cursor: default; }
.view-tabs button:disabled { opacity: 0.6; cursor: not-allowed; }
.tab-note { margin-left: 0.4rem; font-size: 0.75rem; opacity: 0.8; }

.result-stage > .stage-pano { width: 100%; }
.stage-img-wrap { position: relative; display: inline-block; max-width: 100%; line-height: 0; }

/* 圖上的「360° 環景模式」：平常隱藏，hover／鍵盤聚焦才出現；觸控裝置常駐 */
.pano-cta {
  position: absolute;
  left: 50%;
  bottom: 1rem;
  transform: translate(-50%, 6px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.1rem;
  padding: 0.6rem 1.3rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: rgba(20, 18, 14, 0.78);
  color: #fff;
  line-height: 1.3;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.18s, transform 0.18s, background 0.15s;
}
.stage-img-wrap:hover .pano-cta,
.pano-cta:focus-visible { opacity: 1; transform: translate(-50%, 0); }
.pano-cta:hover:not(:disabled) { background: rgba(20, 18, 14, 0.92); }
.pano-cta:disabled { cursor: not-allowed; }
.cta-title { font-size: 0.95rem; font-weight: 600; }
.timing-btn {
  position: absolute;
  right: 0.75rem;
  bottom: 0.75rem;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 50%;
  background: rgba(20, 18, 14, 0.62);
  color: #fff;
  cursor: pointer;
  transition: background 0.16s;
}
.timing-btn:hover { background: rgba(20, 18, 14, 0.9); }
.cta-sub { font-size: 0.72rem; opacity: 0.75; }
@media (hover: none) { .pano-cta { opacity: 1; transform: translate(-50%, 0); } }

.pano-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  border-radius: 8px;
  background: rgba(20, 18, 14, 0.6);
  color: #fff;
  font-size: 0.9rem;
  line-height: 1.4;
}
.pano-overlay p { margin: 0; }
.pano-spinner {
  width: 38px; height: 38px;
  border: 3px solid rgba(255, 255, 255, 0.25);
  border-top-color: #fff;
  border-radius: 50%;
  animation: pano-spin 0.8s linear infinite;
}
@keyframes pano-spin { to { transform: rotate(360deg); } }

.pano-fail {
  position: absolute;
  left: 0.75rem; right: 0.75rem; bottom: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.9rem;
  border-radius: var(--db-radius-chip);
  background: rgba(255, 255, 255, 0.95);
  color: var(--db-danger);
  font-size: 0.85rem;
  line-height: 1.4;
}
.pano-retry {
  margin-left: auto;
  padding: 0.25rem 0.9rem;
  border: 1px solid currentColor;
  border-radius: var(--db-radius-pill);
  background: none;
  color: inherit;
  cursor: pointer;
}
@media (prefers-reduced-motion: reduce) { .pano-spinner { animation: none; } }
.result-stage.is-swapping .result-img { opacity: 0.5; transition: opacity 0.16s; }

.style-swap { margin-top: 0.5rem; }
.style-swap .sub-title { margin-bottom: 0.6rem; }
.swap-row { display: flex; gap: 0.5rem; }   /* 不換行：卡片平分整排寬度，跟圖片區同寬 */
.swap-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  flex: 1 1 0;
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  font-family: var(--db-font-body);
  cursor: pointer;
}
.swap-thumb {
  display: grid;
  place-items: center;
  width: 100%;
  aspect-ratio: 1;
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

/* 微調 */
.tool-title {
  margin: 1.5rem 0 0.85rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.1rem;
  color: var(--db-text);
}
.tool-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.85rem;
}
.tool-btn {
  flex-shrink: 0;
  min-width: 92px;
  padding: 0.45rem 1rem;
  border: 2px solid transparent;
  border-radius: 4px;
  background: var(--db-secondary-2);
  color: #fff;
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 0.98rem;
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s;
}
.tool-btn.active {
  background: var(--db-accent);
  border-color: var(--db-accent-deep);
  color: var(--db-on-accent);
}
.tool-btn:hover:not(.active) { background: #6f6a6a; }

.slider { flex: 1; min-width: 0; accent-color: var(--db-accent); }
.slider-val {
  flex-shrink: 0;
  min-width: 5.5em;
  font-size: 0.8rem;
  color: var(--db-text-soft);
  font-variant-numeric: tabular-nums;
}

.tool-hint {
  margin: 0.25rem 0 0;
  font-size: 0.8rem;
  line-height: 1.65;
  color: var(--db-placeholder);
}

/* 之前沒給高度：RefineCanvas 內部是 width/height:100%，父層沒有實際高度
   時整組畫布會塌縮成圖片的原始像素大小，遠比左欄小、佔不滿右半邊。
   這裡給一個跟畫面高度連動的高度，畫布才會真的填滿右側。 */
.canvas-wrap {
  min-width: 0;
  height: clamp(460px, 66vh, 720px);
}

/* 預算 */
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
.badge {
  padding: 0.15rem 0.6rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-family: var(--db-font-body);
  font-style: normal;
  font-size: 0.72rem;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  margin-left: auto;
}
.link {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  color: var(--db-text-soft);
  font-size: 0.9rem;
  text-decoration: none;
}
.link:hover { color: var(--db-text); }
.count {
  display: inline-grid;
  place-items: center;
  min-width: 18px; height: 18px;
  padding: 0 5px;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-size: 0.68rem;
}

.row {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 1rem;
  align-items: start;
  padding: 1rem 0;
  border-bottom: 1px solid #f0f0f0;
}
.row-label {
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 1.05rem;
  color: var(--db-text);
}

.candidates {
  display: flex;
  gap: 0.85rem;
  overflow-x: auto;
  padding-bottom: 0.4rem;
}
.candidate {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex-shrink: 0;
  width: 168px;
  padding: 0.65rem;
  border: 2px solid #ececec;
  border-radius: var(--db-radius-chip);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, box-shadow 0.16s;
}
.candidate:hover { border-color: var(--db-accent-soft); }
.candidate.selected {
  border-color: var(--db-accent);
  box-shadow: var(--db-shadow-soft);
}

.img-wrap {
  display: grid;
  place-items: center;
  height: 104px;
  border-radius: 6px;
  background: var(--db-chip-soft);
  overflow: hidden;
}
.img-wrap img { max-width: 100%; max-height: 100%; object-fit: contain; }
.img-placeholder {
  padding: 0 0.5rem;
  color: var(--db-placeholder);
  font-size: 0.72rem;
  text-align: center;
}

.name {
  font-size: 0.82rem;
  line-height: 1.4;
  color: var(--db-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.price { font-size: 0.9rem; font-weight: 600; color: var(--db-text); }
.sim { font-size: 0.7rem; color: var(--db-placeholder); }

.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.25rem;
}
.buy {
  color: var(--db-accent-deep);
  font-size: 0.75rem;
  text-decoration: underline;
}
.fav { cursor: pointer; color: var(--db-placeholder); font-size: 1.05rem; line-height: 1; }
.fav.active { color: var(--db-accent); }

.total {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 0.85rem;
  padding: 1.25rem 0 0.5rem;
}
.total-label { color: var(--db-text-soft); font-size: 0.9rem; }
.total-val {
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 1.6rem;
  color: var(--db-text);
  font-variant-numeric: tabular-nums;
}

.note, .hint {
  margin: 0.5rem 0 0;
  color: var(--db-placeholder);
  font-size: 0.8rem;
  line-height: 1.7;
}
.hint { padding: 2rem 0; text-align: center; font-size: 0.95rem; }

/* 頁尾 */
.next-room {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  margin-top: 2rem;
  padding: 1.1rem 1.5rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-accent-soft);
}
.next-room-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 1rem;
}
.next-room-progress { margin: 0; color: var(--db-text-soft); font-size: 0.9rem; }
.next-room-btn { padding: 0.75rem 1.6rem; font-size: 1.02rem; }
.next-room-hint { margin: 0; color: var(--db-text-soft); font-size: 0.78rem; }
.next-room-done {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.05rem;
  color: var(--db-accent-deep, var(--db-text));
}

.collect-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  margin-top: 2rem;
  padding: 1.1rem 1.25rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.collect-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 1.3rem;
  border: 2px solid var(--db-accent);
  border-radius: var(--db-radius-pill);
  background: #fff;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-style: normal;
  font-weight: 500;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.collect-btn:hover:not(:disabled) { background: var(--db-accent-soft); }
.collect-btn.active {
  background: var(--db-accent);
  color: var(--db-on-accent);
}
.collect-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.collect-star { font-size: 1.15rem; line-height: 1; }
.collect-link {
  color: var(--db-accent-deep);
  font-size: 0.88rem;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.collect-error { margin: 0; width: 100%; text-align: center; }
.reset-warn { align-self: center; color: var(--db-danger); font-size: 0.85rem; }

.actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding-top: 1.75rem;
}

/* 跟 .actions 同樣的按鈕排版，但刻意不叫 .actions——StudioView.vue 的
   :deep(.actions) 全域樣式會把它變成貼齊視窗底部的 sticky 工具列，那是給「這一步
   最後的上一步/下一步」用的。這裡是區塊內部的次要動作（重新調整／生成新圖），
   後面還有其他區塊，用 sticky 會在頁面中段撐出一大段空白。 */
.inline-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  padding-top: 1.25rem;
}

@media (max-width: 900px) {
  .stage-row { grid-template-columns: 1fr; }
  .head-actions { margin-left: 0; }
  .row { grid-template-columns: 1fr; }
  .actions { flex-direction: column-reverse; }
  .actions .db-btn { width: 100%; }
}
</style>
