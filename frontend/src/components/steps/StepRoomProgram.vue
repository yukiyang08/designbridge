<script setup>
/**
 * Step: 房型設定（CAD 入口）— 輸入幾房幾廳幾衛幾廚幾陽台＋總坪數，交給
 * /api/generate-room-plan 直接切割整層樓的房間配置。表單沿用 RoomPlanView.vue
 * 那顆獨立工具頁的寫法，只是狀態換成 useDesignFlow 的 cadCounts/cadTotalPing，
 * 生成完後由 submitRoomProgram 自動導去下一步（選房間），不在這裡處理導頁。
 */
import { computed, ref } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { Icon } from '@iconify/vue'
import { roomPhoto, roomIcon } from '@/config/furniture'

const { cadCounts, cadTotalPing, cadExtraRooms, loading, submitRoomProgram, startFlow } = useDesignFlow()

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

    <p class="page-hint">輸入幾房幾廳＋總坪數，自動生成含牆體、門窗與尺寸標註的房間配置平面圖，下一步再選一間房進去編輯家具。</p>

    <div class="form-row">
      <div class="ping-card">
      <div class="ping-main">
        <span class="ping-word-lg">總坪數 約</span>
        <input
          v-model.number="cadTotalPing"
          type="number" min="1" max="200" step="0.5"
          class="db-input ping-input-lg"
          aria-label="總坪數"
        />
        <span class="ping-word-lg">坪</span>
      </div>
      <p class="ping-hint">≈ {{ estimatedM2.toFixed(1) }} m²</p>
      </div>
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
    </div>

    <div class="alt-actions">
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
    <div class="actions">
      <button class="db-btn" :disabled="loading" @click="submitRoomProgram">生成房型配置</button>
    </div>

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
  margin: 0 0 1.75rem;
  text-align: center;
  color: var(--db-text-soft);
  font-size: 0.92rem;
}

/* 上：五種房間的實景照卡，照片上直接調數量（0 間的卡片變暗）｜下：總坪數 */
.form-row { display: flex; flex-direction: column; gap: 1.5rem; }
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
.ping-card {
  align-self: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1.25rem 2.5rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
}

.ping-main {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 0.7rem;
}
.ping-word-lg {
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 1.2rem;
  color: var(--db-text);
}
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

.alt-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.9rem;
  margin-top: 1.75rem;
  padding-top: 1.5rem;
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

@media (max-width: 640px) {
  .count-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .panel-head { justify-content: flex-start; }
  .mode-toggle-wrap { align-items: flex-start; width: 100%; }
  .mode-toggle { width: 100%; }
  .mode-toggle button { flex: 1; justify-content: center; }
  .upload-card { max-width: none; }
}
</style>
