<script setup>
/**
 * Step 生成結果（render ＋ refine ＋ budget 三個舊 step 合併）
 *
 * 原本是三個獨立步驟：3D渲染圖 → 微調編輯 → 預算估計。三者其實都只是圍著同一張
 * 生成圖打轉——StepRender 本來就用 v-if="!result" 在一頁內切換「設定表單／結果」
 * 兩態，submitRefine／fetchQuotation 也都是原地更新 result、不跳頁——所以合併成
 * 一頁並不需要改資料流，只是把三段 UI 疊在同一個 template 裡，由上到下：
 *   1. 結果圖＋一鍵換風格＋360°環景＋設計詳情
 *   2. （微調已併入結果圖：圖右上角「編輯」，見 RefineEditor）
 *   3. 家具預算：候選清單＋總價
 * 「開始新的設計」「收藏這個設計」固定在頁尾最下面。
 *
 * 還沒生成時（!result）沿用原 StepRender 的設定表單（描述/風格推薦/風水/進階設定）。
 */
import { ref, reactive, computed, watch, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import FengshuiPicker from '@/components/FengshuiPicker.vue'
import FengshuiReport from '@/components/FengshuiReport.vue'
import StyleSuggestions from '@/components/StyleSuggestions.vue'
import ImageUpload from '@/components/ImageUpload.vue'
import DesignDetails from '@/components/steps/DesignDetails.vue'
import TimingPanel from '@/components/TimingPanel.vue'
import RefineEditor from '@/components/RefineEditor.vue'
import FurnitureMover from '@/components/FurnitureMover.vue'
import { canMoveFurniture, canUndoMove, undoMove, applyingMove } from '@/composables/design-flow/move'
import { useDesignFlow, ASPECT_OPTIONS, ORIGINAL_STYLE_KEY } from '@/composables/useDesignFlow'
import { spaceInfo, ROOM_TYPE_LABEL } from '@/composables/design-flow/state'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import { API_BASE } from '@/config/api'

// PanoramaViewer 吃 three.js（約 700KB）：只有真的要看環景時才下載。
const PanoramaViewer = defineAsyncComponent(() => import('@/components/PanoramaViewer.vue'))

const {
  planSource, extraPrompt, outputAspect, roomTypeForPlan, roomType,
  editPlacements, fengshuiEnabled, fengshuiReport,
  selectedStyle, noStyleReference, styleRefImage,
  styleOptions, styleLoading, styleError, fetchStyleOptions,
  styleCandidates, candidatesLoading, candidatesError, confirmedStyle, showSuggestions,
  confirmStyle, clearConfirmedStyle, fetchStyleCandidates, showNextRound, scheduleSearch,
  result, loading, submit3D, prevStep,
  swappingStyle, swapStyle, restoreOriginal, styleSwapCache, styleDemoImages,
  panoLoading, panoUrl, panoError, generatePanorama,
  // 預算
  quotationLoading, quotationError, fetchQuotation, resetFlow,
  cadActiveRoomId,
} = useDesignFlow()
const {
  toggle: toggleFavorite,
  isSelected: isFavorited,
} = useFurnitureSelection()

const router = useRouter()

const viewMode = ref('image')   // 'image' | 'pano'
const showDetails = ref(false)
const showTimings = ref(false)
const timingRuns = computed(() => {
  const r = result.value
  if (r?.timing_runs?.length) return r.timing_runs
  if (!r?.timings?.length) return []
  return [{ kind: r.routing_decision === 'design_adjuster' ? 'refine' : 'generate', elapsed_seconds: parseFloat(r.elapsed_time) || 0, timings: r.timings }]
})
const editing = ref(false)      // 在結果圖上直接編輯（塗抹重繪）
const editFull = ref(false)     // 編輯時是否全螢幕

const imageUrl = computed(() => result.value?.generated_image_url || '')
const isSkipPath = computed(() => planSource.value === 'skip')

// 這一步一律在最上面寫出「現在是哪個房間」：整層是房間名稱，其他路徑是房型
const roomTitle = computed(() => {
  const info = spaceInfo()
  // 不排家具路徑沒有平面圖步驟，roomTypeForPlan 沒被設定過，房型要看空間設定選的那個
  const name = planSource.value === 'skip' ? (ROOM_TYPE_LABEL[roomType.value] || info.space_name) : info.space_name
  const d = info.space_dims
  const fmt = n => Math.round(n * 10) / 10
  return { name, dims: d?.w && d?.d ? `${fmt(d.w)} × ${fmt(d.d)} m` : '' }
})
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
// 有平面圖的路徑在上一步就算好健檢報告了，生成後附在結果下方
const showFengshuiReport = computed(() => !!fengshuiReport.value && editPlacements.value.length > 0)

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
function startEdit(full) { moving.value = false; editing.value = true; editFull.value = full }
function stopEdit() { editing.value = false; editFull.value = false }
// ── 在圖上拖曳家具 ────────────────────────────────────────
const moving = ref(false)
function startMove() { stopEdit(); moving.value = true }
// 切到別間房：編輯中的塗抹、選到的家具都屬於舊那張圖，直接結束
watch(cadActiveRoomId, () => { stopEdit(); moving.value = false })

// ── 家具預算 ──────────────────────────────────────────────
const quotation = computed(() => result.value?.quotation_result || null)

// 生成結果一出來（或換風格／微調換了新圖）就自動估價——這三個動作都會把
// result 換成新物件、quotation_result 清掉（見 render.js/refine.js），watch 在這裡
// 補上原本「進到這一步就自動估價」的行為，只是觸發點從「掛載這個 step」換成
// 「result 換了一個沒有報價的新物件」，因為現在已經不會因為換頁而重新掛載。
// fetchQuotation 自己會讓舊的估價作廢，所以這裡不能再用「正在估價就跳過」擋掉：
// 微調或換風格的新圖常常在上一張還在估價時就出來，擋掉的話新圖就永遠不會估價。
watch(result, (r) => {
  if (r && !r.quotation_result) fetchQuotation()
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
  (list) => {
    if (list) list.forEach((_, idx) => { selectedCandidates[idx] = quotation.value?.selected_indices?.[idx] ?? 0 })
  },
  { immediate: true },
)
// 換款的選擇寫回這份報價（selected_indices）：整層總覽加總各房間預算時要用同一份選擇，
// 不然這裡換過款、總覽還是用預設推薦算
watch(selectedCandidates, () => {
  const q = quotation.value
  const list = q?.furniture_list
  if (!list) return
  const saved = list.map((_, i) => q.selected_indices?.[i] ?? 0)
  const now = list.map((_, i) => selectedCandidates[i] ?? 0)
  if (saved.every((v, i) => v === now[i])) return
  result.value = { ...result.value, quotation_result: { ...q, selected_indices: { ...now } } }
}, { deep: true })

// IKEA 商品名常只有代號（MALM、KALLAX），多一個中文類別才看得出是什麼；
// 沒有明確類別時退回偵測到的名稱
const CATEGORY_ZH = {
  sofa: '沙發', table: '桌子', chair: '椅子', lamp: '燈具', rug: '地毯',
  curtain: '窗簾', storage: '收納', shelf: '收納', bed: '床',
}
const categoryLabel = (item) => CATEGORY_ZH[item.category] || item.detected_name
// IKEA 商品全名後面一長串顏色、尺寸（"KALLAX 層架組, 白色, 77x147 公分"）：清單只留第一段，
// 全名放在 title（滑過去看得到）與商品頁；"VIHALS/VIHALS" 這種重複的也去掉
const shortName = (name = '') => name.split(/[,，]/)[0].trim().replace(/^(\S+)\/\1(?=\s|$)/, '$1')

// 候選完全相同的家具（例如同一款 KALLAX 被偵測到 4 次）合併成一行 ×N；
// 換款時同組的每一件一起換，總價仍是逐件加總
const furnitureGroups = computed(() => {
  const groups = new Map()
  ;(quotation.value?.furniture_list || []).forEach((item, idx) => {
    const key = (item.candidates || []).map(c => c.id || c.name).join('|') || `#${idx}`
    if (!groups.has(key)) groups.set(key, { key, item, idxs: [] })
    groups.get(key).idxs.push(idx)
  })
  return [...groups.values()]
})
const groupPick = (g) => selectedCandidates[g.idxs[0]] ?? 0
function setGroupPick(g, ci) { g.idxs.forEach(i => { selectedCandidates[i] = ci }) }

// 目前展開「換款」的那一組
const openRow = ref(null)
watch(quotation, () => { openRow.value = null })
// 向量與關鍵字都沒比到時後端只給一筆 LLM 估價：沒連結、沒圖、similarity 0
const isEstimate = (c) => !c.purchase_url && !c.product_image_url && !(c.similarity > 0)

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
    <header class="room-title">
      <h2 class="room-name">{{ roomTitle.name }}</h2>
      <span v-if="roomTitle.dims" class="room-dims">{{ roomTitle.dims }}</span>
    </header>

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
          rows="7"
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
        :room-type="roomTypeForPlan"
      />

      <!-- 風水開啟時，把這張圖對應配置的健檢報告附在結果下方 -->
      <FengshuiReport
        v-if="showFengshuiReport && fengshuiEnabled"
        :report="fengshuiReport"
        :placements="editPlacements"
        enabled
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
      <!-- 寬螢幕：左圖右清單（清單 sticky）；窄螢幕退回單欄往下排 -->
      <div class="result-grid">

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

        <div class="result-stage" :class="{ 'is-swapping': swappingStyle }">
          <PanoramaViewer v-if="showingPano" :image-url="panoUrl" class="stage-pano" />
          <RefineEditor
            v-else-if="editing && imageUrl"
            v-model:fullscreen="editFull"
            :image-url="imageUrl"
            @close="stopEdit"
          />
          <FurnitureMover
            v-else-if="moving && imageUrl && canMoveFurniture"
            :image-url="imageUrl"
            @close="moving = false"
          />
          <div v-else class="stage-img-wrap">
            <img v-if="imageUrl" :src="imageUrl" alt="生成的 3D 渲染圖" class="result-img" />
            <p v-else class="no-img">生成完成，但沒有取得圖片 URL。</p>

            <div v-if="swappingStyle" class="swap-overlay" role="status">
              <div class="pano-spinner"></div>
              <p>風格變換中…</p>
            </div>

            <!-- 右上角：直接在圖上編輯／全螢幕編輯 -->
            <div v-if="imageUrl && result.task_id" class="img-tools">
              <button
                v-if="canMoveFurniture" type="button" :disabled="swappingStyle"
                title="在圖上直接拖曳家具" @click="startMove"
              >✥ 移動家具</button>
              <button
                v-if="canUndoMove" type="button" :disabled="swappingStyle || applyingMove"
                title="回到移動家具之前的圖" @click="undoMove"
              >↶ 復原移動</button>
              <button type="button" :disabled="swappingStyle" @click="startEdit(false)">✎ 編輯</button>
              <button type="button" :disabled="swappingStyle" title="全螢幕編輯" aria-label="全螢幕編輯" @click="startEdit(true)">⛶</button>
            </div>

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
              v-if="imageUrl && timingRuns.length"
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
                <span v-if="styleSwapCache[opt.value]" class="swap-done" aria-label="已生成">✓</span>
              </span>
              <span class="swap-label">{{ opt.name }}</span>
            </button>
          </div>
          <p v-if="swappingStyle" class="pano-hint">換風格中，沿用同一個房間佈局重新生成…</p>
        </section>

        <!-- 設計詳情（結構化需求 / 風格參數 / 點雲 / raw JSON） -->
        <div class="details-toggle-wrap">
          <button type="button" class="details-toggle" @click="showDetails = !showDetails">
            {{ showDetails ? '▾' : '▸' }} 設計詳情
          </button>
        </div>
        <DesignDetails v-if="showDetails" :result="result" />
        <TimingPanel
          v-if="showTimings && timingRuns.length"
          :runs="timingRuns"
          @close="showTimings = false"
        />

      </section>

      <!-- ── ② 家具預算 ── -->
      <section class="block block-budget">
        <div class="head">
          <h2 class="block-title">家具推薦</h2>
          <button
            v-if="quotation"
            type="button" class="refresh" title="重新估價" aria-label="重新估價"
            :disabled="quotationLoading" @click="fetchQuotation"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21 12a9 9 0 1 1-2.64-6.36M21 4v5h-5" />
            </svg>
          </button>
          <button v-else class="db-btn db-btn--sm" :disabled="quotationLoading" @click="fetchQuotation">
            {{ quotationLoading ? '估價中…' : '取得家具報價' }}
          </button>
        </div>

        <p v-if="quotationError" class="db-error">{{ quotationError }}</p>

        <template v-if="quotation">
          <div class="total">
            <span class="total-label">預算 · {{ quotation.furniture_list.length }} 件</span>
            <span class="total-val">NT$ {{ computedTotal.toLocaleString() }}</span>
          </div>

          <ul class="furn-list">
            <li v-for="g in furnitureGroups" :key="g.key" class="furn">
              <template v-for="c in [g.item.candidates?.[groupPick(g)]]" :key="c?.id || g.key">
                <div v-if="c" class="furn-main">
                  <span class="furn-thumb">
                    <img v-if="c.product_image_url" :src="c.product_image_url" :alt="c.name" />
                    <span v-else class="furn-thumb-empty">無圖</span>
                  </span>
                  <div class="furn-info" :title="g.item.detected_name">
                    <span class="furn-cat">{{ categoryLabel(g.item) }}</span>
                    <a v-if="c.purchase_url" :href="c.purchase_url" target="_blank" rel="noopener" class="name name--link" :title="c.name">{{ shortName(c.name) }}</a>
                    <span v-else class="name" :title="c.name">{{ shortName(c.name) }}</span>
                    <div class="furn-foot">
                      <span class="price">
                        NT$ {{ c.price.toLocaleString() }}
                        <small v-if="g.idxs.length > 1" class="qty">×{{ g.idxs.length }}</small>
                        <small v-if="isEstimate(c)" class="est">AI 估價</small>
                      </span>
                      <span class="furn-side">
                        <button
                          v-if="!isEstimate(c)"
                          type="button"
                          class="fav"
                          :class="{ active: isFavorited(toFavoriteItem(g.item, c)) }"
                          :title="isFavorited(toFavoriteItem(g.item, c)) ? '取消收藏' : '加入收藏'"
                          :aria-label="isFavorited(toFavoriteItem(g.item, c)) ? '取消收藏' : '加入收藏'"
                          @click="toggleFavorite(toFavoriteItem(g.item, c))"
                        >{{ isFavorited(toFavoriteItem(g.item, c)) ? '★' : '☆' }}</button>
                        <button
                          v-if="g.item.candidates.length > 1"
                          type="button" class="swap-btn" :class="{ open: openRow === g.key }"
                          title="換一款" aria-label="換一款"
                          :aria-expanded="openRow === g.key"
                          @click="openRow = openRow === g.key ? null : g.key"
                        >
                          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                            <path d="m17 2 4 4-4 4" /><path d="M3 11v-1a4 4 0 0 1 4-4h14" />
                            <path d="m7 22-4-4 4-4" /><path d="M21 13v1a4 4 0 0 1-4 4H3" />
                          </svg>
                        </button>
                      </span>
                    </div>
                  </div>
                </div>
              </template>

              <!-- 其他候選：點了就換，並自動收合 -->
              <div v-if="openRow === g.key" class="alts">
                <button
                  v-for="(a, ai) in g.item.candidates"
                  :key="ai"
                  type="button"
                  :class="['alt', { selected: groupPick(g) === ai }]"
                  @click="setGroupPick(g, ai); openRow = null"
                >
                  <span class="alt-img">
                    <img v-if="a.product_image_url" :src="a.product_image_url" :alt="a.name" />
                  </span>
                  <span class="alt-name" :title="a.name">{{ shortName(a.name) }}</span>
                  <span class="alt-price">NT$ {{ a.price.toLocaleString() }}</span>
                </button>
              </div>
            </li>
          </ul>
        </template>

        <p v-else-if="quotationLoading" class="hint" role="status">
          正在辨識畫面中的家具並比對 IKEA 商品…約需 30 秒
        </p>
        <p v-else class="hint">
          尚未取得報價，點右上角「取得家具報價」重試。
        </p>
      </section>

      </div>

      <!-- ── 頁尾：開始新的設計 / 上一步（自動存檔不另外宣告，導覽列有「我的設計」） ── -->
      <div class="actions">
        <button class="db-btn db-btn--ghost db-btn--sm" @click="prevStep">← 上一步</button>
        <button v-if="!confirmingReset" class="db-btn db-btn--ghost db-btn--sm" @click="regenerate">重新調整並生成</button>
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

.room-title { display: flex; align-items: baseline; gap: 0.9rem; margin: 0 0 1rem; }
.room-name {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 2rem;
  color: var(--db-text);
}
.room-dims { color: var(--db-text-soft); font-size: 1rem; font-variant-numeric: tabular-nums; }

.block { display: flex; flex-direction: column; }
.result-grid { display: block; }
.block-budget {
  margin-top: 2rem;
  padding-top: 1.75rem;
  border-top: 1px solid #ececec;
}
@media (min-width: 1100px) {
  .result-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(320px, 27vw, 460px);   /* 圖吃掉剩下的寬度，清單固定窄欄 */
    gap: 2rem;
    align-items: start;
  }
  /* 清單跟著捲動；內容比視窗高時自己捲，不撐開整頁 */
  .block-budget {
    position: sticky;
    top: 1rem;
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    margin-top: 0.5rem;   /* 跟左邊圖片頂端對齊（.result-stage 上方有 0.5rem 內距） */
    padding: 1.1rem 1.1rem 0.5rem;
    border: 1px solid #ececec;
    border-radius: var(--db-radius-chip);
    background: #fff;
  }
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

.lead {
  margin: 0 0 0.9rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.9rem;
  color: var(--db-text);
}
.prompt { min-height: 180px; padding: 1rem 1.25rem; font-size: 1.1rem; }

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
  max-height: 75vh;
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

/* 圖右上角的編輯入口：跟 360° 按鈕一樣 hover 才出現，觸控裝置常駐 */
.img-tools {
  position: absolute;
  top: 0.75rem;
  right: 0.75rem;
  display: flex;
  gap: 0.4rem;
}
.img-tools button {
  height: 2.1rem;
  padding: 0 0.8rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: rgba(20, 18, 14, 0.78);
  color: #fff;
  font-size: 0.88rem;
  line-height: 1;
  cursor: pointer;
}
.img-tools button:hover:not(:disabled) { background: rgba(20, 18, 14, 0.92); }
.img-tools button:disabled { cursor: not-allowed; opacity: 0.6; }

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
.result-stage.is-swapping .result-img { opacity: 0.5; filter: blur(4px); transition: opacity 0.16s, filter 0.16s; }
.swap-overlay {
  position: absolute; inset: 0; z-index: 2;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.6rem;
  line-height: 1.4; color: var(--db-text); font-weight: 600; pointer-events: none;
}
.swap-overlay p { margin: 0; padding: 0.3rem 0.9rem; border-radius: var(--db-radius-pill); background: rgba(255, 255, 255, 0.85); }

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
.swap-thumb { position: relative; }
.swap-thumb-empty { font-size: 1.4rem; color: var(--db-placeholder); }
/* 示範圖保持原色讓人看得出風格感，只靠已生成卡片右上角的勾區分 */
.swap-done {
  position: absolute; top: 4px; right: 4px;
  width: 18px; height: 18px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--db-accent); color: #fff; font-size: 0.7rem; line-height: 1;
}
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

/* 預算 */
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.5rem;
}
.head .db-btn, .refresh { margin-left: auto; }
.refresh {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 50%;
  background: none;
  color: var(--db-text-soft);
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.refresh:hover:not(:disabled) { background: var(--db-chip-soft); color: var(--db-text); }
.refresh:disabled { opacity: 0.5; cursor: not-allowed; }

/* 家具清單：每件一行（選中的商品），其他候選按「換」才展開 */
.furn-list { margin: 0; padding: 0; list-style: none; }
.furn { padding: 0.4rem 0; border-bottom: 1px solid #f0f0f0; }
.furn:last-child { border-bottom: none; }
.furn-main { display: flex; align-items: center; gap: 0.75rem; }
.furn-thumb {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 76px;
  height: 76px;
  border-radius: 10px;
  background: var(--db-chip-soft);
  overflow: hidden;
}
.furn-thumb img { max-width: 100%; max-height: 100%; object-fit: contain; }
.furn-thumb-empty { color: var(--db-placeholder); font-size: 0.7rem; }
.furn-info { display: flex; flex-direction: column; gap: 0.15rem; flex: 1; min-width: 0; }
.furn-info .name { font-size: 0.92rem; }
.furn-cat { font-size: 0.74rem; color: var(--db-text-soft); letter-spacing: 0.04em; }
/* 價格在左、收藏／換款在右同一行，操作離資訊近、也看得到 */
.furn-foot { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-top: 0.1rem; }
.est {
  margin-left: 0.4rem;
  padding: 0.05rem 0.4rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  color: var(--db-text-soft);
  font-size: 0.68rem;
  font-weight: 400;
}
.furn-side { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
.name--link { color: inherit; text-decoration: none; }
.name--link:hover { text-decoration: underline; text-underline-offset: 3px; }
.qty {
  margin-left: 0.5rem;
  padding: 0.1rem 0.6rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent-ink);
  color: #fff;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.4;
}
/* 換一款：圓形「交換」圖示，跟旁邊的收藏星號同尺寸；展開候選時反白 */
.swap-btn svg { width: 20px; height: 20px; }
.swap-btn {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: none;
  color: var(--db-text-soft);
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.swap-btn:hover { background: var(--db-chip-soft); color: var(--db-text); }
.swap-btn.open { background: var(--db-accent-ink); color: #fff; }
.swap-btn:focus-visible { outline: 2px solid var(--db-text); outline-offset: 2px; }
.alts {
  display: flex;
  gap: 0.6rem;
  margin-top: 0.7rem;
  padding-bottom: 0.3rem;
  overflow-x: auto;
}
.alt {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  flex-shrink: 0;
  width: 112px;
  padding: 0.5rem;
  border: 2px solid #ececec;
  border-radius: var(--db-radius-chip);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s;
}
.alt:hover { border-color: var(--db-accent-soft); }
.alt.selected { border-color: var(--db-accent); }
.alt-img {
  display: grid;
  place-items: center;
  height: 72px;
  border-radius: 6px;
  background: var(--db-chip-soft);
  overflow: hidden;
}
.alt-img img { max-width: 100%; max-height: 100%; object-fit: contain; }
.alt-name {
  font-size: 0.72rem;
  line-height: 1.35;
  color: var(--db-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.alt-price { font-size: 0.8rem; font-weight: 600; color: var(--db-text); }

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

.fav {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: 50%;
  background: none;
  cursor: pointer;
  color: var(--db-text-soft);
  font-size: 1.75rem;
  line-height: 1;
  transition: background 0.16s, color 0.16s, transform 0.12s;
}
.fav:hover { background: var(--db-chip-soft); color: var(--db-text); }
.fav:active { transform: scale(0.9); }
.fav.active { color: var(--db-accent); }
.fav:focus-visible { outline: 2px solid var(--db-text); outline-offset: 2px; }

.total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.85rem;
  padding: 0.75rem 0 0.6rem;
  border-bottom: 1px solid #f0f0f0;
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

@media (max-width: 900px) {
  .actions { flex-direction: column-reverse; }
  .actions .db-btn { width: 100%; }
}
</style>
