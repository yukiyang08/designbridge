<script setup>
/**
 * Step 01 空間設定 — Figma MacBook Air - 10 的延伸
 *
 * 與設計稿的差異：
 *  · 「描述你想要的空間」併進這一頁。原本描述在下一步，等於先選房型／家具、
 *    翻頁、再打字，而且兩頁綁的是同一個欄位，看起來像被問了兩次。
 *  · 坪數收進「進階設定」：多數情況用預設值就好，擺在主畫面會跟房型搶注意力。
 *  · 其餘設計稿沒畫、但會影響生成結果的欄位（自訂長寬、輸出比例、家具數量）
 *    同樣收在進階設定，一個都沒刪。
 *  · 風水禁忌反過來從進階設定拉回主畫面（FengshuiPicker.vue）：它是會真的搬動
 *    家具的硬約束，跟房型／家具同一個等級，收在摺疊面板裡等於做了沒人用。
 */
import { ref, computed, watch } from 'vue'
import { Icon } from '@iconify/vue'
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import FengshuiPicker from '@/components/FengshuiPicker.vue'
import SpaceSizeFields from '@/components/steps/SpaceSizeFields.vue'
import { ROOM_OPTIONS, FURNITURE_BY_ROOM, roomIcon, roomPhoto, furnitureIcon, furnitureLabel } from '@/config/furniture'
import { useDesignFlow, ASPECT_OPTIONS } from '@/composables/useDesignFlow'

const {
  planSource, roomType, roomTypeForPlan, spaceSizePing, customRoomW, customRoomD, outputAspect,
  furnitureItems, furnitureQty, extraPrompt, fengshuiRules,
  loading, submitLayout, nextStep, scheduleSearch, startFlow,
} = useDesignFlow()

const isSkip = computed(() => planSource.value === 'skip')
const availableFurniture = computed(() => FURNITURE_BY_ROOM[roomType.value] || [])

/* ── 房型 ── */
const customRoomInput = ref('')
const showCustomRoom = ref(false)
const roomChoices = computed(() => {
  // 自訂房型不在 ROOM_OPTIONS 裡，補一顆 chip 才看得到目前選的是它
  const known = ROOM_OPTIONS.some(o => o.value === roomType.value)
  return known ? ROOM_OPTIONS : [...ROOM_OPTIONS, { value: roomType.value, label: roomType.value }]
})

// 每個房型各記一份家具選擇，來回切換不會把選好的清掉
const roomMemory = {}
function pickRoom(value) {
  if (roomType.value === value) return
  roomMemory[roomType.value] = { items: furnitureItems.value, qty: furnitureQty.value }
  const saved = roomMemory[value]
  roomType.value = value
  furnitureItems.value = saved?.items ?? []
  furnitureQty.value = saved?.qty ?? {}
}
function applyCustomRoom() {
  const v = customRoomInput.value.trim()
  if (!v) return
  pickRoom(v)
  customRoomInput.value = ''
  showCustomRoom.value = false
}

/* ── 家具 ── */
const MAX_QTY = 20
const customFurnitureInput = ref('')
const showCustomFurniture = ref(false)

function toggleFurniture(value) {
  if (furnitureItems.value.includes(value)) {
    furnitureItems.value = furnitureItems.value.filter(v => v !== value)
    const q = { ...furnitureQty.value }; delete q[value]; furnitureQty.value = q
  } else {
    furnitureItems.value = [...furnitureItems.value, value]
    furnitureQty.value = { ...furnitureQty.value, [value]: 1 }
  }
}
function addCustomFurniture() {
  const val = customFurnitureInput.value.trim().toLowerCase().replace(/\s+/g, '_')
  if (val && !furnitureItems.value.includes(val)) {
    furnitureItems.value = [...furnitureItems.value, val]
    furnitureQty.value = { ...furnitureQty.value, [val]: 1 }
  }
  customFurnitureInput.value = ''
  showCustomFurniture.value = false
}
function qtyOf(value) { return furnitureQty.value[value] || 1 }
function setQty(value, n) {
  furnitureQty.value = { ...furnitureQty.value, [value]: Math.max(1, Math.min(MAX_QTY, n)) }
}

/* 自訂家具不在 availableFurniture 裡，但要能看到並取消 */
const extraSelected = computed(
  () => furnitureItems.value.filter(v => !availableFurniture.value.some(o => o.value === v)),
)
const furnitureChoices = computed(() => [
  ...availableFurniture.value,
  ...extraSelected.value.map(v => ({ value: v, label: furnitureLabel(v) })),
])

/* ── 範圍檢查：手打的值不受 input 的 min/max 約束，這裡擋住才不會送出奇怪的房間 ── */
const PING_RANGE = [1, 100]
const SIDE_RANGE = [1, 30]   // 公尺
const sizeError = computed(() => {
  const ping = spaceSizePing.value
  if (!(ping >= PING_RANGE[0] && ping <= PING_RANGE[1])) {
    return `坪數需介於 ${PING_RANGE[0]}–${PING_RANGE[1]} 之間`
  }
  for (const [label, v] of [['長', customRoomW.value], ['寬', customRoomD.value]]) {
    if (v != null && v !== '' && !(v >= SIDE_RANGE[0] && v <= SIDE_RANGE[1])) {
      return `${label}度需介於 ${SIDE_RANGE[0]}–${SIDE_RANGE[1]} 公尺之間`
    }
  }
  if ((customRoomW.value > 0) !== (customRoomD.value > 0)) return '請同時填寫長與寬'
  return ''
})
const needFurniture = computed(() => !isSkip.value && !furnitureItems.value.length)
// 按鈕為什麼不能按，直接寫在旁邊，不要等按下去才在卡片底部報錯
const blockReason = computed(() => (needFurniture.value ? '請先選至少 1 件要擺放的家具' : sizeError.value))

/* 描述改在這一頁輸入，風格推薦是下一步才顯示的，所以打字時就先在背景查好，
   翻頁過去不用再等一次。 */
watch(extraPrompt, () => { if (isSkip.value) scheduleSearch() })

/**
 * 跳過家具排版。
 *
 * 只切換路徑、留在這一頁：切成 skip 之後這頁會就地變成「空間類型 + 描述」，
 * 步驟列也從五步縮成四步。不往下跳一步，是因為使用者按這顆按鈕的理由通常是
 * 「還沒想好家具」，這時該讓他先把想要的樣子打出來，而不是直接被推到選風格。
 */
function goSkipRender() {
  // 沒有文字描述時，風格推薦會拿房型當查詢字，而 roomTypeForPlan 平常是
  // generate-layout 回來才設定的；跳過排版就沒人設定它，要在這裡補，
  // 否則不管選哪個房型，推薦出來的都是預設「客廳」。
  roomTypeForPlan.value = roomType.value
  planSource.value = 'skip'
  scheduleSearch()
}

// 跳過之後要能回來：切回排家具路徑，留在同一頁
function goLayoutMode() {
  planSource.value = 'generate'
}

function submit() {
  if (isSkip.value) {
    // 不排家具：這頁沒有東西要送後端，直接進下一步選風格
    roomTypeForPlan.value = roomType.value
    scheduleSearch()
    nextStep()
    return
  }
  submitLayout()
}
</script>

<template>
  <div class="space-setup">
    <!-- 這一步一定是「單間」（AI 排單一房間家具，或不排家具直接生成）；
         點「整層房屋」切去 cad 流程的房型設定步驟（StepRoomProgram.vue）。 -->
    <div class="mode-toggle-wrap">
      <span class="mode-toggle-label">生成範圍</span>
      <div class="mode-toggle" role="group" aria-label="生成範圍">
        <button type="button" class="active">單間</button>
        <button type="button" :disabled="loading" @click="startFlow('cad')">整層房屋</button>
      </div>
    </div>

    <!-- 空間類型：四張實景照併排一列，一眼比較再選 -->
    <!-- ── 空間類型 ── -->
    <section class="room-section">
      <h2 class="db-col-title">空間類型</h2>
      <div class="room-grid">
        <button
          v-for="opt in roomChoices" :key="opt.value"
          type="button"
          :class="['room-card', { 'is-active': roomType === opt.value }]"
          :aria-pressed="roomType === opt.value"
          @click="pickRoom(opt.value)"
        >
          <img v-if="roomPhoto(opt.value)" :src="roomPhoto(opt.value)" :alt="opt.label" class="room-card-photo" loading="lazy" />
          <Icon v-else :icon="roomIcon(opt.value)" class="room-card-icon" aria-hidden="true" />
          <span class="room-card-label">{{ opt.label }}</span>
          <span v-if="roomType === opt.value" class="room-card-check" aria-hidden="true">✓</span>
        </button>

        <!-- 虛線＋「＋」讓它看起來是「可以新增」而不是「已停用」 -->
        <button
          v-if="!showCustomRoom"
          type="button"
          class="room-card room-card--add"
          @click="showCustomRoom = true"
        >
          <span class="room-card-icon" aria-hidden="true">＋</span>
          <span class="room-card-label">自訂</span>
        </button>
      </div>

      <div v-if="showCustomRoom" class="custom-row">
        <input
          v-model="customRoomInput"
          class="db-input"
          placeholder="例如：和室、更衣室"
          autofocus
          @keydown.enter.prevent="applyCustomRoom"
          @keydown.esc="showCustomRoom = false"
        />
        <button type="button" class="add-btn" title="加入" @click="applyCustomRoom">✓</button>
        <button type="button" class="cancel-btn" title="取消" @click="showCustomRoom = false">✕</button>
      </div>
    </section>


    <div v-if="!isSkip" class="columns">

      <!-- ── 預計擺放家具（不排家具模式不需要）── -->
      <section v-if="!isSkip" class="col">
        <h2 class="db-col-title">預計擺放家具</h2>
        <p v-if="needFurniture" class="col-hint">至少選 1 件</p>
        <div class="furniture-list">
          <!-- 選中後 chip 旁出現數量 stepper：數量是主要決定，不該藏在進階設定 -->
          <div v-for="opt in furnitureChoices" :key="opt.value" class="furn-item">
            <button
              type="button"
              :class="['db-chip', 'furniture-chip', { 'is-active': furnitureItems.includes(opt.value) }]"
              :aria-pressed="furnitureItems.includes(opt.value)"
              @click="toggleFurniture(opt.value)"
            >
              <Icon :icon="furnitureIcon(opt.value)" class="chip-icon" aria-hidden="true" />
              <span>{{ opt.label }}</span>
            </button>
            <span v-if="furnitureItems.includes(opt.value)" class="furn-qty" role="group" :aria-label="`${opt.label}數量`">
              <button type="button" class="qty-btn" :aria-label="`減少${opt.label}`" :disabled="qtyOf(opt.value) <= 1" @click="setQty(opt.value, qtyOf(opt.value) - 1)">−</button>
              <span class="qty-num" aria-live="polite">{{ qtyOf(opt.value) }}</span>
              <button type="button" class="qty-btn" :aria-label="`增加${opt.label}`" :disabled="qtyOf(opt.value) >= MAX_QTY" @click="setQty(opt.value, qtyOf(opt.value) + 1)">＋</button>
            </span>
          </div>

          <button
            v-if="!showCustomFurniture"
            type="button"
            class="add-chip"
            @click="showCustomFurniture = true"
          >＋ 自訂</button>
          <div v-else class="custom-row">
            <input
              v-model="customFurnitureInput"
              class="db-input"
              placeholder="家具名稱（英文）"
              autofocus
              @keydown.enter.prevent="addCustomFurniture"
              @keydown.esc="showCustomFurniture = false"
            />
            <button type="button" class="add-btn" title="加入" aria-label="加入" @click="addCustomFurniture">✓</button>
            <button type="button" class="cancel-btn" title="取消" aria-label="取消" @click="showCustomFurniture = false">✕</button>
          </div>
        </div>
      </section>

      <!-- ── 空間大小（排家具路徑才放主畫面）──
           這條路徑的坪數會實際換算成房間長寬去排家具，是要當場決定的東西，
           收進進階設定的話多數人不會展開，等於永遠用預設值排版。
           不排家具路徑的坪數只是折進 prompt 的一句話，留在進階設定就好。 -->
      <section v-if="!isSkip" class="col col-size">
        <h2 class="db-col-title">空間大小</h2>
        <SpaceSizeFields :error="sizeError" />
      </section>
    </div>

    <!-- ══ 風水禁忌 ══
         原本收在進階設定裡，但這些是會實際搬動家具的硬約束，不是微調參數。 -->
    <FengshuiPicker v-model="fengshuiRules" :room-type="roomType" />

    <!-- ══ 描述需求：只有不排家具路徑需要在這裡填 ══
         排家具路徑的描述留在下一步（選風格那頁），第一頁專心決定房型／家具／坪數。 -->
    <section v-if="isSkip" class="describe">
      <h2 class="db-col-title">描述你想要的空間</h2>
      <textarea
        v-model="extraPrompt"
        class="db-textarea"
        rows="3"
        placeholder="例如：木質感、採光充足的明亮感…"
      />
      <p class="describe-hint">
        這段描述會用來搜尋風格參考圖，也會直接影響生成的效果圖。
      </p>
    </section>

    <!-- ══ 進階設定 ══ -->
    <AdvancedPanel :hint="isSkip ? '坪數・長寬・比例' : '輸出比例'">
      <div class="adv-grid">
        <!-- 排家具路徑的空間大小已經在主畫面 -->
        <div v-if="isSkip" class="adv-field adv-span">
          <label class="field-label">空間大小</label>
          <SpaceSizeFields :error="sizeError" />
        </div>

        <div class="adv-field">
          <label class="field-label" for="aspect">輸出圖片長寬比</label>
          <select id="aspect" v-model="outputAspect" class="db-input">
            <option v-for="opt in ASPECT_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>
      </div>
    </AdvancedPanel>

    <div class="actions">
      <button class="db-btn" :disabled="loading || !!blockReason" @click="submit">
        {{ isSkip ? '下一步：選擇風格' : '生成平面圖' }}
      </button>
      <p v-if="blockReason" class="block-hint" role="status">{{ blockReason }}</p>
      <button v-if="!isSkip" type="button" class="skip-btn" :disabled="loading" @click="goSkipRender">
        跳過排版，直接生成渲染圖 →
      </button>
      <button v-else type="button" class="skip-btn" :disabled="loading" @click="goLayoutMode">
        ← 改為排家具佈局
      </button>
    </div>
  </div>
</template>

<style scoped>
.space-setup { display: flex; flex-direction: column; }

/* 單間／整層房屋——跟 StepRoomProgram.vue 的切換鈕同一套視覺，維持步驟之間一致 */
.mode-toggle-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.35rem;
  margin-bottom: 1.25rem;
}
.mode-toggle-label {
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--db-text-soft);
}
.mode-toggle {
  display: inline-flex;
  padding: 4px;
  border: 1px solid #e2ddd0;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.04);
}
.mode-toggle button {
  padding: 0.55rem 1.3rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-display);
  font-style: normal;
  font-weight: 500;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s, box-shadow 0.16s;
}
.mode-toggle button:not(.active):hover { background: rgba(255, 255, 255, 0.7); color: var(--db-text); }
.mode-toggle button:disabled { opacity: 0.5; cursor: not-allowed; }
.mode-toggle button.active {
  background: var(--db-accent);
  color: var(--db-on-accent);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
  cursor: default;
}

/* 排家具路徑三欄（房型／家具／坪數），收窄後置中，不等分整張卡——
   等分會讓內容少的欄下方空一大塊，分隔線又剛好把空白框起來。 */
.columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 340px));
  justify-content: center;
  gap: clamp(1.25rem, 2.5vw, 2.5rem);
  padding-bottom: 1.75rem;
}

/* 欄與欄之間拉一條淡分隔線 */
.col + .col { border-left: 1px solid #f0f0f0; padding-left: clamp(1.5rem, 3vw, 3rem); }
.col { min-width: 0; display: flex; flex-direction: column; align-items: center; }

/* 標題下方一道短的主色線，當作欄位的分組記號 */
.db-col-title { position: relative; padding-bottom: 0.7rem; }
.db-col-title::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: 0;
  width: 34px;
  height: 3px;
  border-radius: 2px;
  background: var(--db-accent);
  transform: translateX(-50%);
}

/* 空間類型：實景照片卡併排成一列（4 間 + 自訂），標題壓在照片底部的漸層上 */
.room-section { display: flex; flex-direction: column; align-items: center; padding-bottom: 2rem; }
.room-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 1rem;
  width: 100%;
  max-width: 1000px;
}
.room-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  aspect-ratio: 4 / 3;
  padding: 0;
  overflow: hidden;
  border: 3px solid transparent;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
  color: var(--db-text);
  cursor: pointer;
  transition: border-color 0.16s, transform 0.12s, box-shadow 0.16s;
}
.room-card:hover { border-color: var(--db-accent); transform: translateY(-2px); }
.room-card:focus-visible { outline: 3px solid var(--db-accent-deep); outline-offset: 2px; }
.room-card.is-active {
  border-color: var(--db-accent);
  box-shadow: 0 0 0 2px var(--db-ink), var(--db-shadow-soft);
}
.room-card-photo {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.4s ease, filter 0.2s;
}
.room-card:hover .room-card-photo { transform: scale(1.04); }
/* 沒選中的照片略微壓暗，選中的那張最亮，視線自然落在它身上 */
.room-card:not(.is-active) .room-card-photo { filter: saturate(0.7); }
.room-card-icon { font-size: 3rem; line-height: 1; margin-bottom: auto; margin-top: 1.5rem; }
.room-card-label {
  position: relative;
  width: 100%;
  padding: 1.6rem 0.5rem 0.65rem;
  background: linear-gradient(to top, rgba(49, 49, 49, 0.78), transparent);
  color: #fff;
  font-family: var(--db-font-display);
  font-style: normal;
  font-weight: 500;
  font-size: 1.25rem;
  text-align: center;
  text-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
}
/* 有照片時：文字置中放大當主角，照片只當壓暗的背景點綴 */
.room-card-photo + .room-card-label {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.5rem;
  background: rgba(35, 35, 35, 0.55);
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.6);
}
.room-card:not(.is-active) .room-card-photo + .room-card-label { transition: background 0.16s; }
.room-card:hover .room-card-photo + .room-card-label { background: rgba(35, 35, 35, 0.45); }
.room-card.is-active .room-card-photo + .room-card-label { background: rgba(201, 196, 187, 0.8); color: #222; text-shadow: none; }
.room-card.is-active .room-card-label { background: linear-gradient(to top, rgba(201, 196, 187, 0.95), transparent); color: var(--db-on-accent); text-shadow: none; }
.room-card-check {
  position: absolute;
  top: 0.55rem;
  right: 0.55rem;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-size: 0.95rem;
  box-shadow: var(--db-shadow-soft);
}
.room-card--add { border: 2px dashed #c9c4bb; background: transparent; color: var(--db-text-soft); justify-content: center; }
.room-card--add .room-card-icon { margin: 0; }
.room-card--add .room-card-label { background: none; color: var(--db-text-soft); text-shadow: none; padding: 0.4rem; }
@media (prefers-reduced-motion: reduce) {
  .room-card:hover, .room-card:hover .room-card-photo { transform: none; }
}

/* 家具：設計稿是單欄直排 */
.furniture-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  align-items: stretch;
  width: 100%;
  max-width: 260px;
}
.furniture-chip {
  justify-content: flex-start;
  gap: 0.55rem;
  padding: 0.55rem 1rem;
}
.chip-icon { font-size: 1.15rem; flex-shrink: 0; }

/* 「＋ 自訂」：虛線外框 = 這格還是空的、可以自己填，不是被停用 */
.add-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.55rem 1rem;
  border: 2px dashed #cfcfcf;
  border-radius: var(--db-radius-chip);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.05rem;
  cursor: pointer;
  transition: border-color 0.16s, color 0.16s, background 0.16s;
}
.add-chip--lg { font-size: 1.25rem; padding: 0.65rem 1rem; }
.add-chip:hover {
  border-color: var(--db-accent);
  color: var(--db-text);
  background: #f7f6f3;
}

.custom-row {
  display: flex;
  gap: 0.4rem;
  width: 100%;
  max-width: 320px;
  margin-top: 0.75rem;
}
.custom-row .db-input { min-width: 0; }
.add-btn,
.cancel-btn {
  flex-shrink: 0;
  width: 40px;
  border: none;
  border-radius: 6px;
  font-size: 1rem;
  cursor: pointer;
}
.add-btn { background: var(--db-accent); color: var(--db-on-accent); }
.add-btn:hover { background: var(--db-accent-deep); }
.cancel-btn { background: var(--db-chip); color: var(--db-text-soft); }
.cancel-btn:hover { background: #cfcfcf; }

/* ── 描述需求 ── */
.describe {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 1.75rem;
  border-top: 1px solid #f0f0f0;
}
.describe .db-textarea { max-width: 720px; }
.describe-hint {
  margin: 0.55rem 0 0;
  max-width: 720px;
  width: 100%;
  font-size: 0.8rem;
  color: var(--db-placeholder);
}

/* ── 進階設定內部 ── */
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
.chip-row { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.chip-row .db-chip { font-size: 0.92rem; padding: 0.4rem 0.9rem; }

/* 家具列：chip 在左、數量 stepper 在右 */
.furn-item { display: flex; align-items: center; gap: 0.4rem; }
.furn-item .furniture-chip { flex: 1; min-width: 0; }
.furn-qty {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 3px;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
}
.qty-btn {
  width: 28px; height: 28px;
  border: none; border-radius: 50%;
  background: #fff;
  color: var(--db-text);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
}
.qty-btn:hover:not(:disabled) { background: var(--db-accent); color: var(--db-on-accent); }
.qty-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.qty-btn:focus-visible { outline: 2px solid var(--db-accent-deep); outline-offset: 1px; }
.qty-num { min-width: 1.6em; text-align: center; font-variant-numeric: tabular-nums; }

.col-hint { margin: -0.3rem 0 0.7rem; font-size: 0.8rem; color: var(--db-text-soft); }
.block-hint { margin: 0; font-size: 0.85rem; color: var(--db-danger); text-align: center; }

.actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.9rem;
  padding-top: 1rem;
}
.actions .db-btn { min-width: 337px; }

/* 次要動作：小一號、只有外框，不跟主按鈕搶視線 */
.skip-btn {
  padding: 0.4rem 1rem;
  border: 1.5px solid #dcdcdc;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-body);
  font-size: 0.84rem;
  cursor: pointer;
  transition: border-color 0.16s, color 0.16s, background 0.16s;
}
.skip-btn:hover:not(:disabled) {
  border-color: var(--db-accent);
  color: var(--db-text);
  background: #f7f6f3;
}
.skip-btn:disabled { opacity: 0.5; cursor: not-allowed; }

@media (max-width: 900px) {
  .columns { grid-template-columns: 1fr; }
  .col + .col { border-left: none; padding-left: 0; padding-top: 1.5rem; border-top: 1px solid #f0f0f0; }
  .actions .db-btn { min-width: 0; width: 100%; }
  .mode-toggle-wrap { align-items: flex-start; width: 100%; }
  .mode-toggle { width: 100%; }
  .mode-toggle button { flex: 1; }
}
</style>
