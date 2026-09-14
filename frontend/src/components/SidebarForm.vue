<script setup>
import { ref, computed } from 'vue'
import { Icon } from '@iconify/vue'
import ImageUpload from './ImageUpload.vue'
import MaskEditor from './MaskEditor.vue'
import { ROOM_OPTIONS, FURNITURE_BY_ROOM, furnitureIcon } from '@/config/furniture'

// ── Step control ──────────────────────────────────────────────
const props = defineProps({
  designStep:          { type: Number,  default: 1 },   // 1 = layout input, 2 = style + 3D
  floorPlanUrl:        { type: String,  default: '' },
  styleOptions:        { type: Array,   default: () => [] },
  styleLoading:        { type: Boolean, default: false },
  styleError:          { type: String,  default: '' },
  matchedStylePreview: { type: Object,  default: null },
  loading:             { type: Boolean, default: false },
  error:               { type: String,  default: '' },
  styleRefImage:       { type: Object,  required: true },
  floorPlanUpload:     { type: Object,  required: true },
  // ── refine 模式（細部編輯）專用 ──
  spaceImage:          { type: Object,  default: null },
  baseImagePreview:    { type: String,  default: null },
})

const emit = defineEmits([
  'submit-layout', 'use-uploaded-plan', 'submit-3d', 'retry-style-options',
  'submit', 'mask-ready',
])

// ── 模式：'design'（兩段式裝潢圖生成） | 'refine'（對已生成圖細部編輯）──
const mode      = defineModel('mode',      { default: 'design' })
const textPrompt = defineModel('textPrompt', { default: '' })
const brushSize  = defineModel('brushSize',  { default: 32 })
const drawMode   = defineModel('drawMode',   { default: 'draw' })

const showMaskEditor = ref(false)

// ── Step 1 models ─────────────────────────────────────────────
const planSource     = defineModel('planSource',     { default: 'generate' })  // 'generate' | 'upload'
const roomType       = defineModel('roomType',       { default: 'living_room' })
const spaceSizePing  = defineModel('spaceSizePing',  { default: 4 })
const customRoomW    = defineModel('customRoomW',    { default: null })   // 公尺，null = 用坪數估算
const customRoomD    = defineModel('customRoomD',    { default: null })
const outputAspect   = defineModel('outputAspect',   { default: 'auto' })

// 面積（坪數換算）固定，改任一邊就用面積反推另一邊——每次修改都重算，不是只填一次。
// 用 @input 直接算，不用 watch：兩個 watch 互相盯著對方欄位很容易繞出回圈，
// @input 只在使用者真的動到那個欄位時觸發一次，天生沒有回圈問題。
function recalcRoomSide(filled, other) {
  if (!filled) return
  const totalM2 = spaceSizePing.value * 3.306
  other.value = Math.round((totalM2 / filled) * 10) / 10
}
function onCustomRoomWInput() { recalcRoomSide(customRoomW.value, customRoomD) }
function onCustomRoomDInput() { recalcRoomSide(customRoomD.value, customRoomW) }
const furnitureItems = defineModel('furnitureItems', { default: () => [] })
const furnitureQty   = defineModel('furnitureQty',   { default: () => ({}) })
const extraPrompt    = defineModel('extraPrompt',    { default: '' })
const familyNeeds    = defineModel('familyNeeds',    { default: () => [] })
const fengshuiRules  = defineModel('fengshuiRules',  { default: () => [] })

const ASPECT_OPTIONS = [
  { value: 'auto', label: '自動' },
  { value: '1:1',  label: '1:1 正方形' },
  { value: '4:3',  label: '4:3 橫式' },
  { value: '3:4',  label: '3:4 直式' },
  { value: '16:9', label: '16:9 寬螢幕' },
  { value: '9:16', label: '9:16 直式寬螢幕' },
]

// ── Step 2 models ─────────────────────────────────────────────
const selectedStyle    = defineModel('selectedStyle',    { default: 'auto' })
const noStyleReference = defineModel('noStyleReference', { default: false })
const styleMethod      = defineModel('styleMethod',      { default: 'ai_analysis' })

// ── Furniture options per room type ───────────────────────────
const availableFurniture = computed(() => FURNITURE_BY_ROOM[roomType.value] || [])

function toggleFurniture(value) {
  if (furnitureItems.value.includes(value)) {
    furnitureItems.value = furnitureItems.value.filter(v => v !== value)
    const q = { ...furnitureQty.value }; delete q[value]; furnitureQty.value = q
  } else {
    furnitureItems.value = [...furnitureItems.value, value]
    furnitureQty.value = { ...furnitureQty.value, [value]: 1 }
  }
}

function removeFurniture(value) {
  furnitureItems.value = furnitureItems.value.filter(v => v !== value)
  const q = { ...furnitureQty.value }; delete q[value]; furnitureQty.value = q
}

function qtyOf(value) { return furnitureQty.value[value] || 1 }
function setQty(value, n) {
  furnitureQty.value = { ...furnitureQty.value, [value]: Math.max(1, Math.min(20, n)) }
}

// custom furniture text input
const customFurnitureInput = ref('')
function addCustomFurniture() {
  const val = customFurnitureInput.value.trim().toLowerCase().replace(/\s+/g, '_')
  if (val && !furnitureItems.value.includes(val)) {
    furnitureItems.value = [...furnitureItems.value, val]
    furnitureQty.value = { ...furnitureQty.value, [val]: 1 }
  }
  customFurnitureInput.value = ''
}

const FAMILY_OPTIONS = [
  { value: 'children',   label: '有小孩' },
  { value: 'wheelchair', label: '有輪椅使用者' },
  { value: 'pets',       label: '有寵物' },
]
const FENGSHUI_OPTIONS = [
  { value: 'bed_not_facing_door',    label: '床不對門' },
  { value: 'sofa_not_back_to_door',  label: '沙發不背門' },
  { value: 'desk_not_facing_window', label: '書桌不背窗' },
]

function toggleFamily(value) {
  familyNeeds.value = familyNeeds.value.includes(value)
    ? familyNeeds.value.filter(v => v !== value)
    : [...familyNeeds.value, value]
}
function toggleFengshui(value) {
  fengshuiRules.value = fengshuiRules.value.includes(value)
    ? fengshuiRules.value.filter(v => v !== value)
    : [...fengshuiRules.value, value]
}

const showAdvanced = ref(false)
</script>

<template>
  <div class="form">

    <!-- ═══ refine 模式：對已生成的圖做細部編輯 ═══════════════ -->
    <template v-if="mode === 'refine'">

      <div class="field">
        <label class="field-label">微調需求</label>
        <textarea
          v-model="textPrompt"
          rows="4"
          placeholder="例如：把沙發換成藍色布藝款式、窗簾改為白色薄紗"
        />
      </div>

      <div class="field">
        <label class="field-label">空間圖片</label>
        <ImageUpload
          v-if="spaceImage"
          label="點擊或拖曳上傳"
          icon="📷"
          :preview="spaceImage.preview"
          @change="spaceImage.onChange"
          @remove="spaceImage.remove"
        />
        <div class="brush-toolbar">
          <span class="brush-title">塗抹想修改的區域</span>
          <div class="brush-btns">
            <button :class="['brush-tool', { active: drawMode === 'draw' }]"  type="button" @click="drawMode = 'draw'">畫筆</button>
            <button :class="['brush-tool', { active: drawMode === 'erase' }]" type="button" @click="drawMode = 'erase'">橡皮擦</button>
          </div>
          <label class="brush-size-label">
            筆刷 {{ brushSize }}px
            <input type="range" v-model.number="brushSize" min="5" max="120" step="5" class="brush-range" />
          </label>
        </div>
      </div>

      <div class="submit-wrap">
        <button class="submit-btn" @click="$emit('submit')" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          <span>{{ loading ? 'AI 生成中...' : '套用微調' }}</span>
        </button>
        <p v-if="error" class="error-msg">{{ error }}</p>
      </div>

    </template>

    <!-- ═══ design 模式：兩段式（2D 平面圖 → 風格 → 3D）═══════ -->
    <template v-else>

    <!-- ─── Step indicator ───────────────────────────────── -->
    <div class="step-indicator">
      <div :class="['step-dot', { active: designStep === 1, done: designStep > 1 }]">
        <span v-if="designStep > 1">✓</span><span v-else>1</span>
      </div>
      <div class="step-line" :class="{ done: designStep > 1 }"></div>
      <div :class="['step-dot', { active: designStep === 2 }]">2</div>
      <div class="step-labels">
        <span>2D 平面圖</span>
        <span>3D 渲染圖</span>
      </div>
    </div>

    <!-- ══════════ STEP 1: Layout inputs ══════════ -->
    <template v-if="designStep === 1">

      <!-- 平面圖來源 -->
      <div class="field">
        <label class="field-label">平面圖來源</label>
        <div class="chip-group mode-toggle">
          <button
            type="button"
            :class="['chip', { active: planSource === 'generate' }]"
            @click="planSource = 'generate'"
          >AI自動生成</button>
          <button
            type="button"
            :class="['chip', { active: planSource === 'upload' }]"
            @click="planSource = 'upload'"
          >上傳平面圖</button>
          <button
            type="button"
            :class="['chip', { active: planSource === 'skip' }]"
            @click="planSource = 'skip'"
          >直接生成</button>
        </div>
      </div>

      <!-- 房間類型 -->
      <div class="field">
        <label class="field-label">房間類型</label>
        <div class="chip-group">
          <button
            v-for="opt in ROOM_OPTIONS" :key="opt.value"
            type="button"
            :class="['chip', { active: roomType === opt.value }]"
            @click="roomType = opt.value; furnitureItems = []; furnitureQty = {}"
          >{{ opt.label }}</button>
        </div>
      </div>

      <!-- 空間坪數 -->
      <div class="field">
        <label class="field-label">
          空間坪數
          <span class="value-badge">{{ spaceSizePing }} 坪</span>
        </label>
        <input type="range" v-model.number="spaceSizePing" min="1" max="20" step="1" />
        <div class="range-hint"><span>1 坪</span><span>20 坪</span></div>
        <div class="ping-hint">≈ {{ Math.round(spaceSizePing * 3.3) }} m²</div>
      </div>

      <!-- 自訂長寬（可選，留空就用坪數估算；填一邊會依坪數自動算另一邊） -->
      <div class="field">
        <label class="field-label">自訂長寬（公尺，可留空）</label>
        <div class="custom-input-row">
          <input type="number" v-model.number="customRoomW" min="1" step="0.1" placeholder="長度（自動）" @input="onCustomRoomWInput" />
          <input type="number" v-model.number="customRoomD" min="1" step="0.1" placeholder="寬度（自動）" @input="onCustomRoomDInput" />
        </div>
        <div class="ping-hint">填一邊，另一邊會依上面的坪數自動算</div>
      </div>

      <!-- 輸出圖片長寬比 -->
      <div class="field">
        <label class="field-label">輸出圖片長寬比</label>
        <select v-model="outputAspect">
          <option v-for="opt in ASPECT_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
      </div>

      <!-- 預計擺放的東西 (僅自動生成模式) -->
      <div v-if="planSource === 'generate'" class="field">
        <label class="field-label">預計擺放的家具</label>
        <div class="furniture-grid">
          <button
            v-for="opt in availableFurniture" :key="opt.value"
            type="button"
            :class="['furniture-box', { active: furnitureItems.includes(opt.value) }]"
            @click="toggleFurniture(opt.value)"
          >
            <Icon :icon="furnitureIcon(opt.value)" class="furniture-box-icon" />
            <span class="furniture-box-label">{{ opt.label }}</span>
          </button>
        </div>
        <!-- Custom input -->
        <div class="custom-input-row">
          <input
            v-model="customFurnitureInput"
            placeholder="自訂家具名稱（英文）"
            @keydown.enter.prevent="addCustomFurniture"
          />
          <button type="button" class="add-btn" @click="addCustomFurniture">+</button>
        </div>
        <div v-if="furnitureItems.length" class="selected-tags">
          <span
            v-for="item in furnitureItems" :key="item"
            class="tag"
          >
            {{ item.replace(/_/g, ' ') }}
            <span class="qty">
              <button type="button" class="qty-btn" @click="setQty(item, qtyOf(item) - 1)">−</button>
              <span class="qty-num">{{ qtyOf(item) }}</span>
              <button type="button" class="qty-btn" @click="setQty(item, qtyOf(item) + 1)">+</button>
            </span>
            <button type="button" class="tag-remove" @click="removeFurniture(item)">×</button>
          </span>
        </div>
      </div>

      <!-- 上傳平面配置圖 (僅上傳模式) -->
      <div v-else-if="planSource === 'upload'" class="field">
        <label class="field-label">上傳 2D 平面配置圖</label>
        <ImageUpload
          label="點擊或拖曳上傳平面圖"
          icon="📐"
          hint="上傳 2D 平面配置圖，AI 會依此模擬渲染樣式"
          :preview="floorPlanUpload.preview"
          @change="floorPlanUpload.onChange"
          @remove="floorPlanUpload.remove"
        />
      </div>

      <!-- 不排家具模式：不需要平面圖也不需要指定家具，直接在此填描述、看 AI 推薦風格 -->
      <template v-else>
        <div class="field">
          <label class="field-label">描述你想要的樣式 <span class="optional">選填</span></label>
          <textarea
            v-model="extraPrompt"
            rows="3"
            placeholder="例如：木質感、採光充足的明亮感..."
          />
        </div>
        <div v-if="matchedStylePreview?.image_url" class="field">
          <label class="field-label">AI 推薦風格</label>
          <div class="matched-preview-img">
            <img :src="matchedStylePreview.image_url" alt="AI 推薦風格參考圖" />
            <div class="matched-label">
              <strong>{{ matchedStylePreview.style_name }}</strong>
              <span class="score">{{ (matchedStylePreview.similarity * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Submit -->
      <div class="submit-wrap">
        <button
          v-if="planSource === 'generate'"
          class="submit-btn" @click="$emit('submit-layout')" :disabled="loading"
        >
          <span v-if="loading" class="spinner"></span>
          <span>{{ loading ? '生成中...' : '生成 2D 平面圖' }}</span>
        </button>
        <button
          v-else-if="planSource === 'upload'"
          class="submit-btn step2-btn" @click="$emit('use-uploaded-plan')"
          :disabled="loading || !floorPlanUpload.preview"
        >
          <span v-if="loading" class="spinner"></span>
          <span>{{ loading ? '渲染中...' : '使用平面圖生成渲染圖' }}</span>
        </button>
        <button
          v-else
          class="submit-btn step2-btn" @click="$emit('submit-3d')" :disabled="loading"
        >
          <span v-if="loading" class="spinner"></span>
          <span>{{ loading ? '生成中...' : '生成渲染圖' }}</span>
        </button>
        <p v-if="error" class="error-msg">{{ error }}</p>
      </div>

    </template>

    <!-- ══════════ STEP 2: Style + 3D ══════════ -->
    <template v-else-if="designStep === 2">

      <!-- Floor plan preview -->
      <div v-if="floorPlanUrl" class="floor-plan-preview">
        <div class="fp-label">Step 1 生成的 2D 平面圖</div>
        <img :src="floorPlanUrl" alt="2D 平面圖" class="fp-img" />
      </div>

      <!-- 其他描述 -->
      <div class="field">
        <label class="field-label">描述你想要的樣式 <span class="optional">選填</span></label>
        <textarea
          v-model="extraPrompt"
          rows="3"
          placeholder="例如：木質感、採光充足的明亮感..."
        />
      </div>

      <!-- 進階設定 -->
      <div class="advanced-wrapper">
        <button type="button" class="advanced-toggle" @click="showAdvanced = !showAdvanced">
          <span>進階設定（家庭結構 / 風水）</span>
          <svg class="advanced-arrow" :class="{ open: showAdvanced }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </button>
        <div v-show="showAdvanced" class="advanced-section">
          <div class="field">
            <label class="field-label">家庭結構</label>
            <div class="chip-group">
              <button v-for="opt in FAMILY_OPTIONS" :key="opt.value" type="button"
                :class="['chip', { active: familyNeeds.includes(opt.value) }]"
                @click="toggleFamily(opt.value)">{{ opt.label }}</button>
            </div>
          </div>
          <div class="field">
            <label class="field-label">風水需求</label>
            <div class="chip-group">
              <button v-for="opt in FENGSHUI_OPTIONS" :key="opt.value" type="button"
                :class="['chip', { active: fengshuiRules.includes(opt.value) }]"
                @click="toggleFengshui(opt.value)">{{ opt.label }}</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 裝潢風格 -->
      <div class="field">
        <label class="field-label">裝潢風格</label>
        <select v-model="selectedStyle" :disabled="styleLoading">
          <option v-for="opt in styleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
        <div v-if="styleLoading" class="status-hint">載入中...</div>
        <div v-if="styleError" class="status-error-row">
          <span class="status-error">{{ styleError }}</span>
          <button type="button" class="retry-btn" @click="emit('retry-style-options')">重試</button>
        </div>
      </div>

      <!-- 風格參考圖 -->
      <div class="field">
        <div class="field-label-row">
          <label class="field-label">風格參考圖</label>
          <label class="toggle-label">
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
          <div v-if="styleRefImage.preview" class="radio-group style-method-group">
            <label :class="{ active: styleMethod === 'ai_analysis' }">
              <input type="radio" v-model="styleMethod" value="ai_analysis" />
              <div class="radio-content">
                <strong>AI 分析風格</strong>
                <small>Gemini 解析色調，注入 prompt</small>
              </div>
            </label>
            <label :class="{ active: styleMethod === 'redux' }">
              <input type="radio" v-model="styleMethod" value="redux" />
              <div class="radio-content">
                <strong>FLUX.1-Redux</strong>
                <small>以圖為主做風格遷移</small>
              </div>
            </label>
            <label :class="{ active: styleMethod === 'ipadapter' }">
              <input type="radio" v-model="styleMethod" value="ipadapter" />
              <div class="radio-content">
                <strong>IP-Adapter</strong>
                <small>圖像注入風格</small>
              </div>
            </label>
          </div>
          <div v-if="!styleRefImage.preview && matchedStylePreview?.image_url" class="matched-preview">
            <div class="matched-label">
              AI 依描述自動選取：<strong>{{ matchedStylePreview.style_name }}</strong>
              <span class="score">{{ (matchedStylePreview.similarity * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </template>
        <div v-else class="no-style-hint">純文字 prompt 生圖，不套用風格參考圖</div>
      </div>

      <!-- Submit -->
      <div class="submit-wrap">
        <button class="submit-btn step2-btn" @click="$emit('submit-3d')" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          <span>{{ loading ? '生成中...' : '生成 3D 渲染圖' }}</span>
        </button>
        <p v-if="error" class="error-msg">{{ error }}</p>
      </div>

    </template>

    </template>

  </div>

  <!-- 遮罩編輯器 Modal（refine 模式） -->
  <MaskEditor
    v-if="showMaskEditor"
    :imageUrl="baseImagePreview"
    @confirm="blob => { $emit('mask-ready', blob); showMaskEditor = false }"
    @cancel="showMaskEditor = false"
  />
</template>

<style scoped>

/* ── refine 模式：遮罩筆刷工具列 ── */
.brush-title { font-size: 0.8rem; font-weight: 700; color: #444; }
.brush-toolbar {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.65rem 0.75rem;
  background: rgba(0,0,0,0.03);
  border: 1.5px solid #ddd;
  border-radius: var(--radius-md);
}
.brush-btns { display: flex; gap: 0.4rem; }
.brush-tool {
  flex: 1;
  padding: 0.35rem 0;
  border: 1.5px solid #ccc;
  border-radius: 8px;
  background: #fff;
  color: #555;
  font-size: 0.8rem;
  font-family: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.brush-tool.active { background: #1c1c1e; color: #fff; border-color: #1c1c1e; }
.brush-size-label {
  font-size: 0.75rem;
  color: #555;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.brush-range { width: 120px; accent-color: #1c1c1e; cursor: pointer; }
.form { display: flex; flex-direction: column; gap: 1.25rem; min-height: 100%; }

/* ── Step indicator ── */
.step-indicator {
  display: grid;
  grid-template-columns: 28px 1fr 28px;
  grid-template-rows: 28px auto;
  align-items: center;
  gap: 0 0;
  margin-bottom: 0.25rem;
}
.step-dot {
  width: 28px; height: 28px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.8rem; font-weight: 700;
  background: #e5e5e5; color: #888;
  transition: all 0.2s;
}
.step-dot.active { background: #1c1c1e; color: #fff; }
.step-dot.done   { background: var(--primary); color: #fff; }
.step-line {
  height: 2px;
  background: #e0e0e0;
  transition: background 0.2s;
}
.step-line.done { background: var(--primary); }
.step-labels {
  grid-column: 1 / -1;
  display: flex;
  justify-content: space-between;
  font-size: 0.7rem;
  color: var(--text-4);
  margin-top: 0.3rem;
}

/* ── Field ── */
.field { display: flex; flex-direction: column; gap: 0.45rem; }
.field-label {
  font-size: 0.8rem; font-weight: 600; color: var(--text-2);
  display: flex; align-items: center; gap: 0.4rem;
}
.optional {
  font-size: 0.7rem; font-weight: 500; color: var(--text-4);
  background: var(--primary-subtle); padding: 0.1rem 0.45rem; border-radius: 99px;
}
.value-badge {
  background: var(--primary-light); color: var(--primary);
  padding: 0.1rem 0.5rem; border-radius: 99px;
  font-size: 0.75rem; font-weight: 700; margin-left: auto;
}

/* ── Range ── */
input[type='range'] { width: 100%; accent-color: var(--primary); cursor: pointer; }
.range-hint { display: flex; justify-content: space-between; font-size: 0.72rem; color: var(--text-4); }
.ping-hint  { font-size: 0.72rem; color: var(--text-3); text-align: right; }

/* ── Chips ── */
.chip-group { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip {
  padding: 0.35rem 0.75rem;
  border: 1.5px solid #d0d0d0; border-radius: 99px;
  font-size: 0.8rem; font-family: inherit; font-weight: 500;
  color: #555; background: #fff; cursor: pointer;
  transition: all 0.15s;
}
.chip:hover { border-color: #999; color: #222; }
.chip.active {
  border-color: #1c1c1e; background: #1c1c1e; color: #fff;
  font-weight: 600; box-shadow: 0 2px 8px rgba(0,0,0,0.18);
}

/* ── Furniture picker: square boxes (icon + label) ── */
.furniture-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));
  gap: 0.5rem;
}
.furniture-box {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.35rem; padding: 0.65rem 0.4rem;
  border: 1.5px solid #d0d0d0; border-radius: 10px;
  background: #fff; color: #555; cursor: pointer;
  font-size: 0.72rem; font-family: inherit; font-weight: 500;
  transition: all 0.15s;
}
.furniture-box:hover { border-color: #999; color: #222; }
.furniture-box.active {
  border-color: #1c1c1e; background: #1c1c1e; color: #fff;
  font-weight: 600; box-shadow: 0 2px 8px rgba(0,0,0,0.18);
}
.furniture-box-icon { font-size: 1.35rem; }
.furniture-box-label { line-height: 1.2; text-align: center; }

/* ── Plan-source segmented toggle ── */
.mode-toggle { gap: 0.5rem; }
.mode-toggle .chip { flex: 1; text-align: center; padding: 0.5rem 0.75rem; }

/* ── Custom furniture input ── */
.custom-input-row {
  display: flex; gap: 0.4rem; margin-top: 0.25rem;
}
.custom-input-row input {
  flex: 1; padding: 0.45rem 0.75rem;
  border: 1.5px solid #ddd0c0; border-radius: var(--radius-md);
  font-size: 0.82rem; font-family: inherit; color: var(--text-1);
  background: rgba(255,250,243,0.75);
}
.custom-input-row input:focus { outline: none; border-color: var(--primary); }
.add-btn {
  padding: 0.45rem 0.85rem;
  border: 1.5px solid #ddd0c0; border-radius: var(--radius-md);
  background: var(--primary-light); color: var(--primary);
  font-size: 1rem; font-weight: 700; cursor: pointer;
  transition: background 0.15s;
}
.add-btn:hover { background: var(--primary); color: #fff; }

/* ── Selected tags ── */
.selected-tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.2rem; }
.tag {
  display: flex; align-items: center; gap: 0.3rem;
  background: var(--primary-light); color: var(--primary);
  border: 1px solid var(--primary-border);
  padding: 0.18rem 0.55rem; border-radius: 99px;
  font-size: 0.75rem; font-weight: 500;
}
.tag-remove {
  background: none; border: none; cursor: pointer;
  color: var(--primary); font-size: 0.85rem; padding: 0;
  line-height: 1; display: flex; align-items: center;
}
.tag-remove:hover { color: #c0392b; }
.qty { display: inline-flex; align-items: center; gap: 0.15rem; }
.qty-btn {
  width: 16px; height: 16px; border-radius: 4px; padding: 0; line-height: 1;
  border: 1px solid var(--primary-border); background: #fff; color: var(--primary);
  cursor: pointer; font-size: 0.8rem; display: flex; align-items: center; justify-content: center;
}
.qty-btn:hover { background: var(--primary); color: #fff; }
.qty-num { min-width: 14px; text-align: center; font-weight: 700; font-size: 0.75rem; }

/* ── Textarea ── */
textarea {
  padding: 0.85rem 1rem; border: 1.5px solid #ddd0c0;
  border-radius: var(--radius-md); resize: vertical;
  font-size: 0.875rem; font-family: inherit; color: var(--text-1);
  line-height: 1.65; background: rgba(255,250,243,0.75);
  transition: border-color 0.18s, box-shadow 0.18s;
}
textarea:focus {
  outline: none; border-color: var(--primary);
  background: #fffaf5; box-shadow: 0 0 0 3px rgba(139,94,60,0.1);
}
textarea::placeholder { color: var(--text-4); }

/* ── Advanced ── */
.advanced-wrapper { display: flex; flex-direction: column; }
.advanced-toggle {
  display: flex; align-items: center; justify-content: space-between;
  width: 100%; padding: 0.6rem 0.9rem;
  background: rgba(0,0,0,0.03); border: 1.5px solid #ddd;
  border-radius: var(--radius-md); color: #555;
  font-size: 0.82rem; font-weight: 600; font-family: inherit;
  cursor: pointer; transition: background 0.18s;
}
.advanced-toggle:hover { background: rgba(0,0,0,0.06); }
.advanced-arrow { transition: transform 0.25s ease; flex-shrink: 0; }
.advanced-arrow.open { transform: rotate(180deg); }
.advanced-section { display: flex; flex-direction: column; gap: 1rem; padding: 1rem 0.25rem 0.25rem; }

/* ── Floor plan preview (step 2) ── */
.floor-plan-preview {
  border: 1.5px solid #c5d8c0; border-radius: var(--radius-md);
  background: rgba(240,250,240,0.7); overflow: hidden;
}
.fp-label {
  font-size: 0.72rem; font-weight: 600; color: #4a7c59;
  padding: 0.45rem 0.75rem; background: rgba(200,240,210,0.5);
  border-bottom: 1px solid #c5d8c0;
}
.fp-img { width: 100%; display: block; max-height: 220px; object-fit: contain; }

/* ── Select ── */
select {
  padding: 0.65rem 0.85rem; border: 1.5px solid #ddd0c0;
  border-radius: var(--radius-md); font-size: 0.875rem;
  font-family: inherit; background: rgba(255,250,243,0.75);
  color: var(--text-1); cursor: pointer; appearance: auto;
}
select:focus { outline: none; border-color: var(--primary); }

/* ── Status hints ── */
.status-hint  { font-size: 0.8rem; color: var(--text-3); }
.status-error-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.status-error { font-size: 0.8rem; color: #c0392b; flex: 1; }
.retry-btn {
  padding: 0.25rem 0.65rem; border: 1px solid #e0b4b4;
  border-radius: var(--radius-sm); background: #fff5f5; color: #c0392b;
  font-size: 0.75rem; font-weight: 600; font-family: inherit; cursor: pointer;
}

/* ── Style toggle ── */
.field-label-row { display: flex; align-items: center; justify-content: space-between; }
.toggle-label {
  display: flex; align-items: center; gap: 0.35rem;
  font-size: 0.75rem; color: #505050; cursor: pointer; font-weight: 600;
}
.toggle-label input[type='checkbox'] { accent-color: var(--primary); cursor: pointer; }
.no-style-hint {
  font-size: 0.78rem; color: var(--text-3);
  padding: 0.55rem 0.75rem; background: var(--primary-subtle);
  border-radius: var(--radius-md); border: 1px dashed var(--primary-border);
}

/* ── Radio group ── */
.radio-group { display: flex; flex-direction: column; gap: 0.4rem; }
.radio-group label {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.6rem 0.85rem; border: 1.5px solid #ddd0c0;
  border-radius: var(--radius-md); cursor: pointer;
  background: rgba(255,250,243,0.65); transition: all 0.18s;
}
.radio-group label:hover { border-color: var(--primary-border); }
.radio-group label.active { border-color: var(--primary); background: var(--primary-light); }
.radio-group input[type='radio'] { accent-color: var(--primary); flex-shrink: 0; }
.radio-content { display: flex; flex-direction: column; gap: 0.05rem; }
.radio-content strong { font-size: 0.83rem; font-weight: 600; color: var(--text-1); }
.radio-content small  { font-size: 0.72rem; color: var(--text-3); }
.style-method-group { margin-top: 0.25rem; }
.style-method-group label { padding: 0.45rem 0.75rem; }

/* Matched preview */
.matched-preview { margin-top: 0.15rem; }
.matched-label {
  font-size: 0.75rem; color: var(--primary);
  display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;
}
.score {
  background: var(--primary-light); color: var(--primary);
  padding: 0.05rem 0.4rem; border-radius: 99px; font-size: 0.7rem; font-weight: 600;
}

/* Matched preview with thumbnail (skip 模式) */
.matched-preview-img {
  display: flex; flex-direction: column; gap: 0.4rem;
  border: 1.5px solid #ddd0c0; border-radius: var(--radius-md);
  padding: 0.6rem; background: rgba(255,250,243,0.65);
}
.matched-preview-img img {
  width: 100%; max-height: 160px; object-fit: cover;
  border-radius: var(--radius-sm);
}
.matched-preview-img .matched-label { color: var(--text-2); }
.matched-preview-img .matched-label strong { color: var(--primary); }

/* ── Submit ── */
.submit-wrap {
  position: sticky; bottom: 0; margin-top: auto;
  padding-top: 1.25rem; padding-bottom: 0.25rem;
  background: linear-gradient(to top, rgba(255,248,240,1) 65%, rgba(255,248,240,0));
}
.submit-btn {
  width: 100%; padding: 0.9rem 1rem;
  background: #1c1c1e; color: white;
  border: none; border-radius: var(--radius-lg);
  font-size: 0.95rem; font-weight: 700; font-family: inherit;
  cursor: pointer; display: flex; align-items: center;
  justify-content: center; gap: 0.5rem;
  transition: all 0.2s; letter-spacing: 0.02em;
  box-shadow: 0 4px 16px rgba(0,0,0,0.22);
}
.submit-btn:hover:not(:disabled) {
  transform: translateY(-1px); background: #333;
  box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}
.submit-btn:disabled { opacity: 0.6; cursor: not-allowed; box-shadow: none; transform: none; }
.step2-btn { background: linear-gradient(135deg, #8B5E3C 0%, #b07845 100%); }
.step2-btn:hover:not(:disabled) { background: linear-gradient(135deg, #7a5233 0%, #9c6a3a 100%); }

.spinner {
  width: 15px; height: 15px;
  border: 2px solid rgba(255,255,255,0.35);
  border-top-color: white; border-radius: 50%;
  animation: spin 0.75s linear infinite; flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.error-msg {
  font-size: 0.82rem; color: #c0392b;
  background: #fff5f5; padding: 0.55rem 0.8rem;
  margin-top: 0.5rem; border-radius: var(--radius-sm); border: 1px solid #f5c6c6;
}
</style>
