<script setup>
/**
 * Step 01 空間設定 — Figma MacBook Air - 10 的延伸
 *
 * 與設計稿的差異：
 *  · 「描述你想要的空間」併進這一頁。原本描述在下一步，等於先選房型／家具、
 *    翻頁、再打字，而且兩頁綁的是同一個欄位，看起來像被問了兩次。
 *  · 坪數收進「進階設定」：多數情況用預設值就好，擺在主畫面會跟房型搶注意力。
 *  · 其餘設計稿沒畫、但會影響生成結果的欄位（自訂長寬、輸出比例、家具數量、
 *    家庭結構、風水）同樣收在進階設定，一個都沒刪。
 */
import { ref, computed, watch } from 'vue'
import { Icon } from '@iconify/vue'
import AdvancedPanel from '@/components/shell/AdvancedPanel.vue'
import { ROOM_OPTIONS, FURNITURE_BY_ROOM, furnitureIcon, furnitureLabel } from '@/config/furniture'
import {
  useDesignFlow, ASPECT_OPTIONS, FAMILY_OPTIONS, FENGSHUI_OPTIONS,
} from '@/composables/useDesignFlow'

const {
  planSource, roomType, roomTypeForPlan, spaceSizePing, customRoomW, customRoomD, outputAspect,
  furnitureItems, furnitureQty, extraPrompt, familyNeeds, fengshuiRules,
  loading, submitLayout, nextStep, scheduleSearch,
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

function pickRoom(value) {
  if (roomType.value === value) return
  roomType.value = value
  furnitureItems.value = []
  furnitureQty.value = {}
}
function applyCustomRoom() {
  const v = customRoomInput.value.trim()
  if (!v) return
  pickRoom(v)
  customRoomInput.value = ''
  showCustomRoom.value = false
}

/* ── 家具 ── */
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
function removeFurniture(value) {
  furnitureItems.value = furnitureItems.value.filter(v => v !== value)
  const q = { ...furnitureQty.value }; delete q[value]; furnitureQty.value = q
}
function qtyOf(value) { return furnitureQty.value[value] || 1 }
function setQty(value, n) {
  furnitureQty.value = { ...furnitureQty.value, [value]: Math.max(1, Math.min(20, n)) }
}

/* 自訂家具不在 availableFurniture 裡，但要能看到並取消 */
const extraSelected = computed(
  () => furnitureItems.value.filter(v => !availableFurniture.value.some(o => o.value === v)),
)

/* ── 坪數 ↔ 自訂長寬連動（沿用舊 SidebarForm 的 @input 做法，避免兩個 watch 互咬）── */
function recalcRoomSide(filled, other) {
  if (!filled) return
  const totalM2 = spaceSizePing.value * 3.306
  other.value = Math.round((totalM2 / filled) * 10) / 10
}
function onCustomRoomWInput() { recalcRoomSide(customRoomW.value, customRoomD) }
function onCustomRoomDInput() { recalcRoomSide(customRoomD.value, customRoomW) }

/**
 * 由坪數推得的房間長寬，鏡射 api.py generate_layout 的算法
 * （1 坪 = 3.306 m²，長寬比 5:4）。
 */
const derivedSize = computed(() => {
  if (customRoomW.value && customRoomD.value) {
    return { w: customRoomW.value, d: customRoomD.value, custom: true }
  }
  const totalM2 = (spaceSizePing.value || 0) * 3.306
  if (totalM2 <= 0) return null
  return {
    w: Math.round(Math.sqrt(totalM2 * 5 / 4) * 10) / 10,
    d: Math.round(Math.sqrt(totalM2 * 4 / 5) * 10) / 10,
    custom: false,
  }
})

function toggleIn(listRef, value) {
  listRef.value = listRef.value.includes(value)
    ? listRef.value.filter(v => v !== value)
    : [...listRef.value, value]
}

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
    <div class="columns" :class="{ 'one-col': isSkip }">

      <!-- ── 空間類型 ── -->
      <section class="col">
        <h2 class="db-col-title">空間類型</h2>
        <div class="room-grid">
          <button
            v-for="opt in roomChoices" :key="opt.value"
            type="button"
            :class="['db-chip', 'db-chip--lg', { 'is-active': roomType === opt.value }]"
            @click="pickRoom(opt.value)"
          >{{ opt.label }}</button>

          <!-- 虛線＋「＋」讓它看起來是「可以新增」而不是「已停用」 -->
          <button
            v-if="!showCustomRoom"
            type="button"
            class="add-chip add-chip--lg"
            @click="showCustomRoom = true"
          >＋ 自訂</button>
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

      <!-- ── 預計擺放家具（不排家具模式不需要）── -->
      <section v-if="!isSkip" class="col">
        <h2 class="db-col-title">預計擺放家具</h2>
        <div class="furniture-list">
          <button
            v-for="opt in availableFurniture" :key="opt.value"
            type="button"
            :class="['db-chip', 'furniture-chip', { 'is-active': furnitureItems.includes(opt.value) }]"
            @click="toggleFurniture(opt.value)"
          >
            <Icon :icon="furnitureIcon(opt.value)" class="chip-icon" aria-hidden="true" />
            <span>{{ opt.label }}</span>
            <span v-if="furnitureItems.includes(opt.value) && qtyOf(opt.value) > 1" class="qty-badge">
              ×{{ qtyOf(opt.value) }}
            </span>
          </button>

          <!-- 自訂家具（設計稿有這顆 chip，但沒給輸入流程）-->
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
            <button type="button" class="add-btn" title="加入" @click="addCustomFurniture">✓</button>
            <button type="button" class="cancel-btn" title="取消" @click="showCustomFurniture = false">✕</button>
          </div>

          <!-- 自訂加進來的項目也要能看到／取消 -->
          <button
            v-for="v in extraSelected" :key="v"
            type="button"
            class="db-chip furniture-chip is-active"
            @click="removeFurniture(v)"
          >
            <Icon :icon="furnitureIcon(v)" class="chip-icon" aria-hidden="true" />
            <span>{{ furnitureLabel(v) }}</span>
            <span v-if="qtyOf(v) > 1" class="qty-badge">×{{ qtyOf(v) }}</span>
          </button>
        </div>
      </section>

      <!-- ── 空間大小（排家具路徑才放主畫面）──
           這條路徑的坪數會實際換算成房間長寬去排家具，是要當場決定的東西，
           收進進階設定的話多數人不會展開，等於永遠用預設值排版。
           不排家具路徑的坪數只是折進 prompt 的一句話，留在進階設定就好。 -->
      <section v-if="!isSkip" class="col col-size">
        <h2 class="db-col-title">空間大小</h2>
        <div class="ping-main">
          <span class="ping-word-lg">約</span>
          <input
            v-model.number="spaceSizePing"
            type="number" min="1" max="100" step="0.5"
            class="db-input ping-input-lg"
            aria-label="空間坪數"
          />
          <span class="ping-word-lg">坪</span>
        </div>
        <p class="ping-hint">≈ {{ Math.round((spaceSizePing || 0) * 3.3) }} m²</p>

        <div v-if="derivedSize" class="size-readout">
          <span class="readout-label">{{ derivedSize.custom ? '自訂長寬' : '換算約' }}</span>
          <span class="readout-val">{{ derivedSize.w }} × {{ derivedSize.d }} <small>公尺</small></span>
        </div>
      </section>
    </div>

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
    <AdvancedPanel hint="坪數・長寬・比例・數量・家庭結構・風水">
      <div class="adv-grid">
        <!-- 排家具路徑的坪數已經在主畫面，這裡不重複 -->
        <div v-if="isSkip" class="adv-field">
          <label class="field-label" for="ping">空間坪數</label>
          <div class="ping-row">
            <span class="ping-word">約</span>
            <input
              id="ping"
              v-model.number="spaceSizePing"
              type="number" min="1" max="100" step="0.5"
              class="db-input ping-input"
            />
            <span class="ping-word">坪</span>
          </div>
          <p v-if="derivedSize" class="field-hint">
            {{ derivedSize.custom ? '自訂長寬' : '換算約' }}
            {{ derivedSize.w }} × {{ derivedSize.d }} 公尺
            （≈ {{ Math.round((spaceSizePing || 0) * 3.3) }} m²）
          </p>
        </div>

        <div class="adv-field">
          <label class="field-label">自訂長寬（公尺，可留空）</label>
          <div class="pair">
            <input
              v-model.number="customRoomW" type="number" min="1" step="0.1"
              class="db-input" placeholder="長度（自動）" @input="onCustomRoomWInput"
            />
            <input
              v-model.number="customRoomD" type="number" min="1" step="0.1"
              class="db-input" placeholder="寬度（自動）" @input="onCustomRoomDInput"
            />
          </div>
          <p class="field-hint">填一邊，另一邊會依上面的坪數自動算</p>
        </div>

        <div class="adv-field">
          <label class="field-label" for="aspect">輸出圖片長寬比</label>
          <select id="aspect" v-model="outputAspect" class="db-input">
            <option v-for="opt in ASPECT_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
        </div>

        <div v-if="!isSkip && furnitureItems.length" class="adv-field adv-span">
          <label class="field-label">已選家具與數量</label>
          <div class="qty-list">
            <span v-for="item in furnitureItems" :key="item" class="qty-tag">
              {{ furnitureLabel(item) }}
              <button type="button" class="qty-btn" @click="setQty(item, qtyOf(item) - 1)">−</button>
              <span class="qty-num">{{ qtyOf(item) }}</span>
              <button type="button" class="qty-btn" @click="setQty(item, qtyOf(item) + 1)">＋</button>
              <button type="button" class="qty-remove" title="移除" @click="removeFurniture(item)">×</button>
            </span>
          </div>
        </div>

        <div class="adv-field">
          <label class="field-label">家庭結構</label>
          <div class="chip-row">
            <button
              v-for="opt in FAMILY_OPTIONS" :key="opt.value" type="button"
              :class="['db-chip', { 'is-active': familyNeeds.includes(opt.value) }]"
              @click="toggleIn(familyNeeds, opt.value)"
            >{{ opt.label }}</button>
          </div>
        </div>

        <div class="adv-field">
          <label class="field-label">風水需求</label>
          <div class="chip-row">
            <button
              v-for="opt in FENGSHUI_OPTIONS" :key="opt.value" type="button"
              :class="['db-chip', { 'is-active': fengshuiRules.includes(opt.value) }]"
              @click="toggleIn(fengshuiRules, opt.value)"
            >{{ opt.label }}</button>
          </div>
        </div>
      </div>
    </AdvancedPanel>

    <div class="actions">
      <button class="db-btn" :disabled="loading" @click="submit">
        {{ isSkip ? '下一步：選擇風格' : '生成平面圖' }}
      </button>
      <button v-if="!isSkip" type="button" class="skip-btn" :disabled="loading" @click="goSkipRender">
        跳過排版，直接生成渲染圖 →
      </button>
    </div>
  </div>
</template>

<style scoped>
.space-setup { display: flex; flex-direction: column; }

/* 排家具路徑三欄（房型／家具／坪數），收窄後置中，不等分整張卡——
   等分會讓內容少的欄下方空一大塊，分隔線又剛好把空白框起來。 */
.columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 280px));
  justify-content: center;
  gap: clamp(1.25rem, 2.5vw, 2.5rem);
  padding-bottom: 1.75rem;
}
/* 不排家具路徑只有房型一欄 */
.columns.one-col { grid-template-columns: minmax(0, 340px); }

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

/* 空間類型：2 欄。chip 不拉滿整欄，拉滿會變成一排「列」而不是可選的標籤 */
.room-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
  width: 100%;
  max-width: 320px;
}
.room-grid .db-chip { width: 100%; padding-inline: 0.5rem; }

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

.qty-badge {
  margin-left: auto;
  font-family: var(--db-font-body);
  font-style: normal;
  font-size: 0.8rem;
  opacity: 0.9;
}

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
  background: #fbfaf6;
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

/* ── 空間大小（主畫面版）── */
.ping-main {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.7rem;
}
.ping-word-lg {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.4rem;
  color: var(--db-text);
}
/* 白底 + 外框，看起來才像可以打字的欄位 */
.ping-input-lg {
  width: 120px;
  height: 58px;
  border: 2px solid var(--db-chip);
  border-radius: 8px;
  background: #fff;
  text-align: center;
  font-size: 1.5rem;
  font-variant-numeric: tabular-nums;
}
.ping-input-lg:focus { border-color: var(--db-accent); background: #fff; }

.ping-hint {
  margin: 0.6rem 0 0;
  text-align: center;
  font-size: 0.85rem;
  color: var(--db-text-soft);
}

.size-readout {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  margin-top: 1.1rem;
  padding: 0.7rem 1rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}
.readout-label { font-size: 0.75rem; color: var(--db-text-soft); }
.readout-val {
  font-family: var(--db-font-display);
  font-size: 1.1rem;
  color: var(--db-text);
  font-variant-numeric: tabular-nums;
}
.readout-val small { font-size: 0.78rem; color: var(--db-text-soft); }

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
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }

.field-label {
  display: block;
  margin-bottom: 0.45rem;
  font-size: 0.88rem;
  font-weight: 500;
  color: var(--db-text-soft);
}
.field-hint {
  margin: 0.4rem 0 0;
  font-size: 0.78rem;
  color: var(--db-placeholder);
}

.ping-row { display: flex; align-items: center; gap: 0.6rem; }
.ping-word { font-size: 0.95rem; color: var(--db-text-soft); }
.ping-input {
  width: 110px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.chip-row { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.chip-row .db-chip { font-size: 0.92rem; padding: 0.4rem 0.9rem; }

.qty-list { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.qty-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.3rem 0.5rem 0.3rem 0.75rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip-soft);
  font-size: 0.88rem;
}
.qty-btn {
  width: 22px; height: 22px;
  border: none; border-radius: 50%;
  background: #fff;
  color: var(--db-text);
  cursor: pointer;
  line-height: 1;
}
.qty-btn:hover { background: var(--db-accent); color: var(--db-on-accent); }
.qty-num { min-width: 1.1em; text-align: center; font-variant-numeric: tabular-nums; }
.qty-remove {
  border: none; background: none; cursor: pointer;
  color: var(--db-placeholder); font-size: 1rem; line-height: 1;
}
.qty-remove:hover { color: var(--db-danger); }

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
  background: #fbfaf6;
}
.skip-btn:disabled { opacity: 0.5; cursor: not-allowed; }

@media (max-width: 900px) {
  .columns,
  .columns.one-col { grid-template-columns: 1fr; }
  .col + .col { border-left: none; padding-left: 0; padding-top: 1.5rem; border-top: 1px solid #f0f0f0; }
  .actions .db-btn { min-width: 0; width: 100%; }
}
</style>
