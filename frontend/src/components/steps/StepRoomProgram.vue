<script setup>
/**
 * Step: 房型設定 ＋ 選擇房間（CAD 入口，合併成一頁）— 輸入幾房幾廳幾衛幾廚幾陽台
 * ＋總坪數，交給 /api/generate-room-plan 直接切割整層樓的房間配置。表單沿用
 * RoomPlanView.vue 那顆獨立工具頁的寫法，只是狀態換成 useDesignFlow 的
 * cadCounts/cadTotalPing。
 *
 * 生成完（cadPlanResult 有值）後，房間選擇器直接在表單下方展開，不跳頁——
 * 原本是獨立的「選擇房間」步驟（StepRoomPick 的 cad 分支），合併過來後這裡
 * 同時擁有兩邊的狀態／邏輯（pendingRoom 兩段式放棄確認、整層一起生成）。
 */
import { computed, ref } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { Icon } from '@iconify/vue'
import { roomPhoto, roomIcon } from '@/config/furniture'
import RoomPickerCad from '@/components/RoomPickerCad.vue'
import ApplyToRooms from '@/components/steps/ApplyToRooms.vue'
import StyleSuggestions from '@/components/StyleSuggestions.vue'
import { API_BASE } from '@/config/api'

const {
  cadCounts, cadTotalPing, cadExtraRooms, loading, submitRoomProgram, startFlow,
  cadPlanResult, cadActiveRoomId, cadRoomStatus, handleCadRoomSelected, abandonCadRoom,
  extraPrompt, cadBatchRunning,
  showSuggestions, styleCandidates, candidatesLoading, candidatesError, confirmedStyle,
  confirmStyle, clearConfirmedStyle, fetchStyleCandidates, showNextRound, scheduleSearch,
} = useDesignFlow()

// 有一間做到一半（還沒渲染完）：這時選別間會被擋，把原因和出口直接擺在畫面上
const pendingRoom = computed(() => {
  const id = cadActiveRoomId.value
  if (!id || cadRoomStatus.value[id] === 'done') return null
  return cadPlanResult.value?.rooms?.find(r => r.id === id) || null
})
const confirmingAbandon = ref(false)   // 兩段式確認，跟歷史紀錄的刪除一致
function onAbandon() {
  if (!confirmingAbandon.value) { confirmingAbandon.value = true; return }
  confirmingAbandon.value = false
  abandonCadRoom()
}

const PING_TO_M2 = 3.305785

const COUNT_FIELDS = [
  { key: 'bedroom_count', room: 'bedroom', label: '臥室' },
  { key: 'living_count', room: 'living_room', label: '客廳' },
  { key: 'dining_count', room: 'dining', label: '餐廳' },
  { key: 'bathroom_count', room: 'bathroom', label: '衛浴' },
  { key: 'kitchen_count', room: 'kitchen', label: '廚房' },
  { key: 'balcony_count', room: 'balcony', label: '陽台' },
]

const newRoomName = ref('')
const showAddRoom = ref(false)
function addExtraRoom() {
  const v = newRoomName.value.trim()
  if (v) cadExtraRooms.value = [...cadExtraRooms.value, v]
  newRoomName.value = ''
  showAddRoom.value = false
}
function removeExtraRoom(i) { cadExtraRooms.value = cadExtraRooms.value.filter((_, idx) => idx !== i) }

const estimatedM2 = computed(() => (cadTotalPing.value || 0) * PING_TO_M2)

function setCount(key, delta) {
  cadCounts.value = { ...cadCounts.value, [key]: Math.max(0, Math.min(10, cadCounts.value[key] + delta)) }
}
</script>

<template>
  <div class="room-program-step">
    <div class="panel-head">
      <h2 class="panel-title">房型設定</h2>

      <!-- 總坪數：不獨立成一行，折進標題列省垂直空間 -->
      <div class="ping-inline">
        <label class="ping-inline-label" for="cad-total-ping">總坪數 約</label>
        <input
          id="cad-total-ping"
          v-model.number="cadTotalPing"
          type="number" min="1" max="200" step="0.5"
          class="db-input ping-input"
        />
        <span class="ping-inline-suffix">坪 ≈ {{ estimatedM2.toFixed(1) }} m²</span>
      </div>

      <!-- 這一步預設是「整層房屋」（CAD 房型切割）；點「單間」直接切到原本單房間
           2D 平面圖流程（StepSpaceSetup），不用先填整層房型再回頭選。 -->
      <div class="mode-toggle-wrap">
        <span class="mode-toggle-label">生成範圍</span>
        <div class="mode-toggle" role="group" aria-label="生成範圍">
          <button type="button" :disabled="loading" @click="startFlow('generate')">單間</button>
          <button type="button" class="active">整層房屋</button>
        </div>
      </div>
    </div>

    <p class="page-hint">輸入幾房幾廳，自動生成含牆體、門窗與尺寸標註的房間配置平面圖，下一步再選一間房進去編輯家具。</p>

    <div class="count-grid">
      <div v-for="f in COUNT_FIELDS" :key="f.key" :class="['count-card', { 'is-zero': !cadCounts[f.key] }]">
        <img v-if="roomPhoto(f.room)" :src="roomPhoto(f.room)" :alt="f.label" class="count-photo" loading="lazy" />
        <Icon v-else :icon="roomIcon(f.room)" class="count-icon" aria-hidden="true" />
        <span class="count-label">{{ f.label }}</span>
        <div class="count-stepper">
          <button type="button" class="count-btn" :aria-label="`減少${f.label}`" @click="setCount(f.key, -1)">−</button>
          <span class="count-num" aria-live="polite">{{ cadCounts[f.key] }}</span>
          <button type="button" class="count-btn" :aria-label="`增加${f.label}`" @click="setCount(f.key, 1)">＋</button>
        </div>
      </div>

      <!-- 自訂空間：名稱自取，每次新增 1 間，點 ✕ 移除 -->
      <div v-for="(name, i) in cadExtraRooms" :key="name + i" class="count-card count-card--extra">
        <span class="count-label">{{ name }}</span>
        <button type="button" class="extra-remove" :aria-label="`移除${name}`" @click="removeExtraRoom(i)">✕</button>
      </div>
      <div v-if="showAddRoom" class="count-card count-card--extra count-card--add">
        <input
          v-model="newRoomName" class="db-input" maxlength="12" placeholder="空間名稱，如：書房"
          autofocus @keydown.enter="addExtraRoom" @keydown.esc="showAddRoom = false"
        />
        <button type="button" class="db-btn" @click="addExtraRoom">加入</button>
      </div>
      <button v-else type="button" class="count-card count-card--extra count-card--add" @click="showAddRoom = true">
        <span class="count-label">＋ 自訂空間</span>
      </button>
    </div>

    <!-- 生成按鈕緊跟在房間數量卡片下面、靠右放，不再套用全域 sticky 的 .actions
         樣式——這個合併後的長頁面裡，sticky-bottom 的按鈕會跟下面的選房間區塊
         搶位置，撐出一大段空白，所以這裡改用一般（非 sticky）的靠右按鈕。 -->
    <div class="generate-row">
      <button type="button" class="db-btn" :disabled="loading" @click="submitRoomProgram">
        {{ cadPlanResult ? '重新生成房型配置' : '生成房型配置' }}
      </button>
    </div>

    <!-- 已經生成過配置就不用再提示這個替代入口——那時使用者要的是往下選房間，
         不是重新選一條路，留著只會把平面圖往下擠。 -->
    <div v-if="!cadPlanResult" class="alt-actions">
      <span class="alt-divider">或者</span>
      <button type="button" class="upload-card" :disabled="loading" @click="startFlow('upload')">
        <span class="upload-icon" aria-hidden="true">📐</span>
        <span class="upload-text">
          <span class="upload-title">上傳我自己的 CAD 平面配置圖</span>
          <span class="upload-desc">已有設計師的平面圖？直接上傳，AI 幫你辨識房間與家具</span>
        </span>
        <span class="upload-arrow" aria-hidden="true">→</span>
      </button>
    </div>

    <!-- 生成完成後，房間選擇器直接在表單下方展開——原本是獨立的「選擇房間」步驟，
         合併過來後不用再跳頁，使用者點房間就直接進平面圖編輯。 -->
    <section v-if="cadPlanResult" class="room-pick">
      <h3 class="room-pick-title">選擇要生成的房間</h3>

      <div v-if="pendingRoom" class="pending-bar" role="status">
        <span class="pending-text">「{{ pendingRoom.label_zh }}」還沒完成渲染，完成後才能換下一間。</span>
        <button type="button" class="db-btn db-btn--sm" @click="handleCadRoomSelected(pendingRoom)">繼續編輯</button>
        <button type="button" class="db-btn db-btn--ghost db-btn--sm" @click="onAbandon" @blur="confirmingAbandon = false">
          {{ confirmingAbandon ? '確定放棄？進度會清除' : '放棄這間，改選其他' }}
        </button>
      </div>

      <RoomPickerCad
        :svg-markup="cadPlanResult.svg_markup || ''"
        :rooms="cadPlanResult.rooms || []"
        @select-room="handleCadRoomSelected"
      />

      <!-- 整層一起生成：描述在這裡填一次，所有房間共用 -->
      <div v-if="!pendingRoom" class="whole-floor">
        <label class="whole-label" for="whole-prompt">描述你理想中的整戶房屋風格</label>
        <textarea
          id="whole-prompt"
          v-model="extraPrompt"
          class="db-textarea"
          rows="2"
          :disabled="cadBatchRunning"
          placeholder="例如：木質感、採光充足的明亮感，整戶統一"
          @input="scheduleSearch"
        />

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

        <ApplyToRooms whole />
      </div>
    </section>

  </div>
</template>

<style scoped>
.room-program-step { display: flex; flex-direction: column; }

.panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
.panel-title {
  margin: 0;
  padding: 0.6rem 1.5rem;
  border-radius: 4px;
  background: var(--db-secondary-2);
  color: #fff;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.25rem;
}

/* 總坪數：折進標題列，不再獨立佔一整行 */
.ping-inline {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-right: auto;   /* 緊跟標題，跟右邊的單間/整層切換保持距離 */
}
.ping-inline-label {
  font-size: 0.88rem;
  color: var(--db-text-soft);
}
.ping-input {
  width: 72px;
  height: 36px;
  padding: 0 0.4rem;
  text-align: center;
  font-size: 1rem;
  font-variant-numeric: tabular-nums;
}
.ping-inline-suffix {
  font-size: 0.82rem;
  color: var(--db-placeholder);
  white-space: nowrap;
}

/* 單間／整層房屋——加大字級/圖示/邊框，跟其他次要控制項區分開，一眼看出這是
   可以切換的模式選擇，不是裝飾用的標籤。 */
.mode-toggle-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.35rem;
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

.page-hint {
  margin: 0 0 1rem;
  text-align: center;
  color: var(--db-text-soft);
  font-size: 0.92rem;
}

/* 五種房間的實景照卡，照片上直接調數量（0 間的卡片變暗） */
.count-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 1rem;
}
.count-card {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
  box-shadow: 0 0 0 2px var(--db-accent), var(--db-shadow-soft);
  transition: box-shadow 0.16s;
}
.count-card.is-zero { box-shadow: none; }
.count-photo {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: filter 0.2s;
}
.count-card.is-zero .count-photo { filter: grayscale(0.85) brightness(0.8); }
.count-stepper { position: relative; }
.count-label {
  position: absolute;
  inset: 0 0 3rem 0;  /* 留出底部 stepper 的高度，文字在照片上方區域正中央 */
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(35, 35, 35, 0.4);
  pointer-events: none;
  color: #fff;
  font-family: var(--db-font-display);
  font-style: normal;
  font-weight: 700;
  font-size: 2rem;
  letter-spacing: 0.04em;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.6);
}
.count-stepper {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.45rem 0.9rem 0.7rem;
  background: rgba(49, 49, 49, 0.8);
  color: #fff;
}
.count-card--extra { background: var(--db-chip-soft); align-items: center; justify-content: center; box-shadow: 0 0 0 2px var(--db-accent); }
.count-card--extra .count-label { position: static; background: none; color: var(--db-text); text-shadow: none; inset: auto; font-size: 1.6rem; }
.count-card--add { border: 2px dashed #c9c4bb; box-shadow: none; gap: 0.5rem; padding: 0.75rem; cursor: pointer; }
.count-card--add .count-label { color: var(--db-text-soft); }
.extra-remove { position: absolute; top: 0.5rem; right: 0.5rem; width: 28px; height: 28px; border: none; border-radius: 50%; background: #fff; cursor: pointer; }

.count-icon { position: absolute; top: 28%; left: 50%; transform: translate(-50%, -50%); font-size: 3.2rem; color: var(--db-text-soft); }
.count-btn {
  width: 32px; height: 32px;
  border: none; border-radius: 50%;
  background: #fff;
  color: var(--db-text);
  font-size: 1.1rem;
  line-height: 1;
  cursor: pointer;
  transition: background 0.16s;
}
.count-btn:hover { background: var(--db-accent); color: var(--db-on-accent); }
.count-btn:focus-visible { outline: 3px solid var(--db-accent); outline-offset: 2px; }
.count-num {
  min-width: 1.4em;
  text-align: center;
  font-family: var(--db-font-num);
  font-variant-numeric: tabular-nums;
  font-size: 1.35rem;
}
.generate-row {
  display: flex;
  justify-content: center;
  margin-top: 0.85rem;
}

.alt-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
  margin-top: 0.75rem;
  padding-top: 0.85rem;
  border-top: 1px solid #ececec;
}
.alt-divider {
  font-size: 0.8rem;
  color: var(--db-placeholder);
}

.upload-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  width: 100%;
  max-width: 560px;
  padding: 1rem 1.25rem;
  border: 2px solid #dcdcdc;
  border-radius: var(--db-radius-card, 16px);
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s, transform 0.12s;
}
.upload-card:hover {
  border-color: var(--db-accent);
  background: #f7f6f3;
  transform: translateY(-2px);
}
.upload-card:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

.upload-icon {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--db-chip-soft);
  font-size: 1.4rem;
}
.upload-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}
.upload-title {
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.02rem;
  color: var(--db-text);
}
.upload-desc {
  font-size: 0.82rem;
  color: var(--db-text-soft);
  line-height: 1.4;
}
.upload-arrow {
  flex-shrink: 0;
  color: var(--db-accent-deep, var(--db-accent));
  font-size: 1.2rem;
}

.room-pick {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #ececec;
}
.room-pick-title {
  margin: 0 0 0.6rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.1rem;
  color: var(--db-text);
}

.pending-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 1rem;
  padding: 0.7rem 1rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
  font-size: 0.9rem;
}
.pending-text { flex: 1 1 14rem; color: var(--db-text); }

.whole-floor { margin-top: 1.5rem; padding-top: 1.25rem; border-top: 1px solid #f0f0f0; }
.whole-label { display: block; margin-bottom: 0.4rem; font-size: 0.88rem; color: var(--db-text-soft); }
.suggest { margin-top: 1rem; }

@media (max-width: 640px) {
  .count-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .panel-head { justify-content: flex-start; }
  .mode-toggle-wrap { align-items: flex-start; width: 100%; }
  .mode-toggle { width: 100%; }
  .mode-toggle button { flex: 1; justify-content: center; }
  .upload-card { max-width: none; }
}
</style>
