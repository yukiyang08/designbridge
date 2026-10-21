<script>
import { ref } from 'vue'
// 平面圖是依哪一組設定生成的。生成時整頁會被 LoadingState 取代、元件會卸載重掛，
// 所以記在模組層，重掛後還認得「設定有沒有在生成後又被改過」。
const generatedSig = ref(null)
</script>

<script setup>
/**
 * Step: 房型設定 ＋ 選擇房間（CAD 入口，合併成一頁）— 輸入幾房幾廳幾衛幾廚幾陽台
 * ＋總坪數，交給 /api/generate-room-plan 直接切割整層樓的房間配置。表單沿用
 * RoomPlanView.vue 那顆獨立工具頁的寫法，只是狀態換成 useDesignFlow 的
 * cadCounts/cadTotalPing。
 *
 * 版面：左邊是設定（桌機固定在畫面上），右邊是平面圖；改了設定馬上看得到「平面圖已過期」。
 * 生成完（cadPlanResult 有值）後，房間選擇器直接在右邊展開，不跳頁——
 * 原本是獨立的「選擇房間」步驟（StepRoomPick 的 cad 分支），合併過來後這裡
 * 同時擁有兩邊的狀態／邏輯（pendingRoom 兩段式放棄確認）。
 */
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import { Icon } from '@iconify/vue'
import { roomPhoto, roomIcon } from '@/config/furniture'
import RoomPickerCad from '@/components/RoomPickerCad.vue'

const {
  cadCounts, cadTotalPing, cadRoomW, cadRoomD, cadExtraRooms, loading, submitRoomProgram, fetchRoomPlan, startFlow,
  cadPlanResult, cadActiveRoomId, cadRoomStatus, cadRendering, cadBatchRunning, handleCadRoomSelected, abandonCadRoom,
} = useDesignFlow()

// 有一間做到一半（還沒渲染完）：這時選別間會被擋，把原因和出口直接擺在畫面上
// 整層資料來自上傳的平面圖（不是房型設定產生的）
const isUploaded = computed(() => cadPlanResult.value?.source === 'upload')

const pendingRoom = computed(() => {
  const id = cadActiveRoomId.value
  if (!id || cadRoomStatus.value[id] === 'done' || cadRendering.value[id]) return null
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

// ── 總坪數與長寬連動：改坪數 → 依目前長寬比例重算長寬；改長或寬 → 重算坪數 ──
const ASPECT = 1.25   // 沒指定長寬時後端用的外框長寬比（roomplan/constants.py 的 BOUNDING_ASPECT_RATIO）
const SIZE_MIN = 3, SIZE_MAX = 60, PING_MIN = 1, PING_MAX = 200
const r1 = (n) => Math.round(n * 10) / 10
const r2 = (n) => Math.round(n * 100) / 100
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))
const num = (e) => parseFloat(e.target.value)

function sizeFromPing(ping, ratio) {
  const d = Math.sqrt((ping * PING_TO_M2) / ratio)
  return { w: r2(d * ratio), d: r2(d) }
}
// 第一次進來（或舊草稿沒有長寬）：由坪數推出
if (!(cadRoomW.value > 0 && cadRoomD.value > 0)) {
  const { w, d } = sizeFromPing(cadTotalPing.value || 32, ASPECT)
  cadRoomW.value = w
  cadRoomD.value = d
}
// 打字的當下就連動（只處理有效數字，打到一半的空字串或 0 先不動它）；超出範圍的留到離開欄位才修正，
// 不然打「25」時第一個字 2 就被拉回最小值，根本打不下去。
function onPing(e) {
  const v = num(e)
  if (!(v > 0)) return
  cadTotalPing.value = v
  const ratio = cadRoomW.value / cadRoomD.value || ASPECT
  const { w, d } = sizeFromPing(v, ratio)
  cadRoomW.value = w
  cadRoomD.value = d
}
function onW(e) {
  const v = num(e)
  if (!(v > 0)) return
  cadRoomW.value = v
  cadTotalPing.value = r1((v * cadRoomD.value) / PING_TO_M2)
}
function onD(e) {
  const v = num(e)
  if (!(v > 0)) return
  cadRoomD.value = v
  cadTotalPing.value = r1((cadRoomW.value * v) / PING_TO_M2)
}
function commitSize() {   // 離開欄位：把超出範圍的修正回來，三個數字重新對齊
  cadRoomW.value = clamp(cadRoomW.value || SIZE_MIN, SIZE_MIN, SIZE_MAX)
  cadRoomD.value = clamp(cadRoomD.value || SIZE_MIN, SIZE_MIN, SIZE_MAX)
  cadTotalPing.value = r1((cadRoomW.value * cadRoomD.value) / PING_TO_M2)
}
function commitPing() {
  const ping = clamp(cadTotalPing.value || PING_MIN, PING_MIN, PING_MAX)
  cadTotalPing.value = ping
  const { w, d } = sizeFromPing(ping, cadRoomW.value / cadRoomD.value || ASPECT)
  cadRoomW.value = clamp(w, SIZE_MIN, SIZE_MAX)
  cadRoomD.value = clamp(d, SIZE_MIN, SIZE_MAX)
}
const sizeValid = computed(() =>
  cadRoomW.value >= SIZE_MIN && cadRoomW.value <= SIZE_MAX &&
  cadRoomD.value >= SIZE_MIN && cadRoomD.value <= SIZE_MAX &&
  cadTotalPing.value >= PING_MIN && cadTotalPing.value <= PING_MAX)

function setCount(key, delta) {
  cadCounts.value = { ...cadCounts.value, [key]: Math.max(0, Math.min(10, cadCounts.value[key] + delta)) }
}

// ── 改了設定就即時更新平面圖 ──
// 後端的房型配置是純規則運算、毫秒級，不需要手動按「生成」。例外：已經有設計中／完成的房間時，
// 重新生成會把它們全部清掉，所以那種情況不自動更新，改成要使用者明確確認（見 onApplyChanges）。
const sig = computed(() => JSON.stringify([cadCounts.value, cadTotalPing.value, cadRoomW.value, cadRoomD.value, cadExtraRooms.value]))
const hasProgress = computed(() =>
  !!cadActiveRoomId.value || Object.keys(cadRoomStatus.value || {}).length > 0 || cadBatchRunning.value)
const dirty = computed(() =>
  !!cadPlanResult.value && hasProgress.value && generatedSig.value !== null && generatedSig.value !== sig.value)

const refreshing = ref(false)
const planError = ref('')
let refreshSeq = 0
let refreshTimer = null
async function refreshPlan() {
  const mine = ++refreshSeq
  refreshing.value = true
  planError.value = ''
  try {
    const data = await fetchRoomPlan()
    if (mine !== refreshSeq) return   // 又改了設定，這份已經過時
    cadPlanResult.value = data
    generatedSig.value = sig.value
  } catch (e) {
    if (mine === refreshSeq) planError.value = e.message   // 例如坪數太小放不下、沒有任何房間；保留舊的平面圖
  } finally {
    if (mine === refreshSeq) refreshing.value = false
  }
}
watch(sig, () => {
  clearTimeout(refreshTimer)
  if (!sizeValid.value || hasProgress.value) return
  refreshTimer = setTimeout(refreshPlan, 450)   // 打字中不要每個字都打一次後端
})

// 已有進度時改設定：要明確確認才套用（會清掉已設計的房間）
const confirmingApply = ref(false)
function onApplyChanges() {
  if (!confirmingApply.value) { confirmingApply.value = true; return }
  confirmingApply.value = false
  generatedSig.value = sig.value
  editing.value = false
  submitRoomProgram()
}

// ── 窄螢幕：生成之後把設定收成一行摘要，讓平面圖佔滿畫面 ──
const narrow = ref(false)
const editing = ref(false)
const foldable = computed(() => narrow.value && !!cadPlanResult.value)
const summary = computed(() => {
  const parts = COUNT_FIELDS.filter(f => cadCounts.value[f.key]).map(f => `${cadCounts.value[f.key]} ${f.label}`)
  parts.push(...cadExtraRooms.value)
  return `${parts.join('、')}　·　${cadTotalPing.value || 0} 坪（${cadRoomW.value}×${cadRoomD.value} m）`
})
let mq = null
const onMq = () => { narrow.value = mq.matches }
onMounted(() => {
  if (!cadPlanResult.value) { generatedSig.value = null; if (sizeValid.value) refreshPlan() }   // 一進來就先給一張預設平面圖
  else if (generatedSig.value === null) generatedSig.value = sig.value
  mq = window.matchMedia('(max-width: 960px)')
  onMq()
  mq.addEventListener('change', onMq)
})
onBeforeUnmount(() => { mq?.removeEventListener('change', onMq); clearTimeout(refreshTimer) })

// ── 平面圖下方的房間標籤：文字版的選房間入口（手機、鍵盤、讀屏都用得到），也標出進度 ──
const rooms = computed(() => cadPlanResult.value?.rooms || [])
const doneCount = computed(() => rooms.value.filter(r => cadRoomStatus.value[r.id] === 'done').length)
function chipState(r) {
  if (cadRoomStatus.value[r.id] === 'done') return 'done'
  if (cadRendering.value[r.id]) return 'rendering'
  if (cadRoomStatus.value[r.id] === 'active') return 'active'   // 設計到一半（含先切去別間的）
  return 'todo'
}
const STATE_TEXT = { done: '已完成', active: '設計中', rendering: '渲染中…' }
// 還沒開始任何一間時，客廳是最適合先做的（它的風格會被其他房間沿用）
const suggestedId = computed(() =>
  !doneCount.value && !cadActiveRoomId.value ? rooms.value.find(r => r.room_type === 'living_room')?.id : null)
</script>

<template>
  <div class="room-program-step" :class="{ 'is-uploaded': isUploaded }">
    <!-- ── 左：設定 ───────────────────────────────────────── -->
    <!-- 平面圖是使用者上傳的（見 cad.js enterUploadedWholeFloor）：沒有幾房幾廳可調，整個隱藏 -->
    <aside v-if="!isUploaded" class="setup" aria-label="房型設定">
      <div class="setup-head">
        <h2 class="setup-title">房型設定</h2>
        <!-- 這一步預設是「整層房屋」（CAD 房型切割）；點「單間」直接切到原本單房間
             2D 平面圖流程（StepSpaceSetup），不用先填整層房型再回頭選。 -->
        <div class="mode-toggle" role="group" aria-label="生成範圍">
          <button type="button" :disabled="loading" @click="startFlow('generate')">單間</button>
          <button type="button" class="active" aria-pressed="true">整層房屋</button>
        </div>
      </div>

      <button v-if="foldable && !editing" type="button" class="setup-summary" @click="editing = true">
        <span class="summary-text">{{ summary }}</span>
        <span class="summary-edit">修改</span>
      </button>

      <div v-show="!foldable || editing" class="setup-body">
        <!-- 空間大小：總坪數與長寬連動，改任何一個，另外兩個馬上跟著變 -->
        <div class="size-block">
          <div class="ping-row">
            <label class="size-label" for="cad-total-ping">總坪數 約</label>
            <input
              id="cad-total-ping" :value="cadTotalPing" type="number"
              :min="PING_MIN" :max="PING_MAX" step="0.5" class="db-input size-input"
              @input="onPing" @change="commitPing"
            />
            <span class="size-unit">坪</span>
            <span class="ping-suffix">≈ {{ estimatedM2.toFixed(1) }} m²</span>
          </div>
          <div class="dim-row">
            <div class="dim-fields">
              <label class="size-label" for="cad-room-w">長</label>
              <input
                id="cad-room-w" :value="cadRoomW" type="number" :min="SIZE_MIN" :max="SIZE_MAX" step="0.1"
                class="db-input size-input" @input="onW" @change="commitSize"
              />
              <span class="dim-x" aria-hidden="true">×</span>
              <label class="size-label" for="cad-room-d">寬</label>
              <input
                id="cad-room-d" :value="cadRoomD" type="number" :min="SIZE_MIN" :max="SIZE_MAX" step="0.1"
                class="db-input size-input" @input="onD" @change="commitSize"
              />
              <span class="size-unit">m</span>
            </div>
          </div>
          <p v-if="!sizeValid" class="size-error" role="alert">
            長寬要在 {{ SIZE_MIN }}–{{ SIZE_MAX }} 公尺、坪數 {{ PING_MIN }}–{{ PING_MAX }} 之間。
          </p>
          <p v-else class="size-hint">改坪數會依目前的長寬比例調整長寬；改長或寬則會更新坪數。</p>
        </div>

        <ul class="count-list">
          <li v-for="f in COUNT_FIELDS" :key="f.key" :class="['count-row', { 'is-zero': !cadCounts[f.key] }]">
            <span class="count-thumb">
              <img v-if="roomPhoto(f.room)" :src="roomPhoto(f.room)" :alt="''" loading="lazy" />
              <Icon v-else :icon="roomIcon(f.room)" aria-hidden="true" />
            </span>
            <span class="count-name">{{ f.label }}</span>
            <span class="count-stepper">
              <button type="button" class="count-btn" :aria-label="`減少${f.label}`" @click="setCount(f.key, -1)">−</button>
              <span class="count-num" aria-live="polite">{{ cadCounts[f.key] }}</span>
              <button type="button" class="count-btn" :aria-label="`增加${f.label}`" @click="setCount(f.key, 1)">＋</button>
            </span>
          </li>

          <!-- 自訂空間：名稱自取，每次新增 1 間，點 ✕ 移除 -->
          <li v-for="(name, i) in cadExtraRooms" :key="name + i" class="count-row count-row--extra">
            <span class="count-thumb count-thumb--text" aria-hidden="true">＋</span>
            <span class="count-name">{{ name }}</span>
            <button type="button" class="extra-remove" :aria-label="`移除${name}`" @click="removeExtraRoom(i)">✕</button>
          </li>
          <li v-if="showAddRoom" class="count-row count-row--add">
            <input
              v-model="newRoomName" class="db-input add-input" maxlength="12" placeholder="空間名稱，如：書房"
              autofocus @keydown.enter="addExtraRoom" @keydown.esc="showAddRoom = false"
            />
            <button type="button" class="db-btn db-btn--sm" @click="addExtraRoom">加入</button>
          </li>
          <li v-else>
            <button type="button" class="add-row" @click="showAddRoom = true">＋ 自訂空間</button>
          </li>
        </ul>

        <!-- 沒有進度時：改任何設定，右邊平面圖會即時更新，不需要按鈕；
             已經有設計中／完成的房間時：套用變更會把它們清掉，所以要明確按、而且要再確認一次 -->
        <p class="live-note" role="status">
          <template v-if="refreshing">更新平面圖中…</template>
          <template v-else-if="planError"><span class="live-error">{{ planError }}</span></template>
          <template v-else-if="hasProgress">已經有設計的房間，改設定不會自動更新平面圖。</template>
          <template v-else>改任何設定，右邊的平面圖會即時更新。</template>
        </p>
        <button
          v-if="dirty" type="button" class="db-btn generate-btn"
          :disabled="loading || !sizeValid" @click="onApplyChanges" @blur="confirmingApply = false"
        >{{ confirmingApply ? '確定？已設計的房間會清除' : '套用變更並重新開始' }}</button>
      </div>
    </aside>

    <!-- ── 右：平面圖 ─────────────────────────────────────── -->
    <section class="plan-pane" :class="{ 'is-stale': dirty }" aria-label="平面圖">
      <!-- 平面圖還沒出來：一進頁面會自動產生，所以通常只會短暫看到；失敗時顯示原因 -->
      <div v-if="!cadPlanResult" class="plan-empty">
        <svg class="empty-glyph" viewBox="0 0 120 84" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
          <rect x="6" y="6" width="108" height="72" rx="3" />
          <path d="M6 44h46M52 6v38M52 44v34M84 6v26M84 32h30M84 32v46" />
        </svg>
        <p class="empty-title">{{ planError ? '還沒辦法產生平面圖' : '產生平面圖中…' }}</p>
        <p v-if="planError" class="empty-error">{{ planError }}</p>
        <p v-else class="empty-sub">依左邊的設定切割空間，約一秒。</p>
        <button type="button" class="upload-btn" :disabled="loading" title="已有設計師的平面圖？AI 幫你辨識房間與家具" @click="startFlow('upload')">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>
            上傳自己的 CAD 平面圖
          </button>
      </div>

      <template v-else>
        <header class="plan-head">
          <div class="plan-head-text">
          <h3 class="plan-title">點一間房，開始設計</h3>
          <p class="plan-sub">
            <template v-if="doneCount">已完成 {{ doneCount }} / {{ rooms.length }} 間。</template>
            <template v-else>建議從客廳開始。做完一間後，可以一鍵把這間的風格套用到其他房間。</template>
          </p>
          <p v-for="w in (isUploaded && cadPlanResult.warnings) || []" :key="w" class="plan-sub plan-warn">{{ w }}</p>
          </div>
          <button type="button" class="upload-btn" :disabled="loading" title="已有設計師的平面圖？AI 幫你辨識房間與家具" @click="startFlow('upload')">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>
            {{ isUploaded ? '重新上傳平面圖' : '上傳自己的 CAD 平面圖' }}
          </button>
        </header>

        <div v-if="dirty" class="stale-banner" role="status">
          <span>設定已經變更，這張平面圖還是舊的。</span>
          <button type="button" class="link-btn" :disabled="loading" @click="onApplyChanges" @blur="confirmingApply = false">
            {{ confirmingApply ? '確定？已設計的房間會清除' : '套用變更並重新開始' }}
          </button>
        </div>

        <div v-if="pendingRoom" class="pending-bar" role="status">
          <span class="pending-text">「{{ pendingRoom.label_zh }}」還沒渲染完成，你的編輯已保留，可以隨時切去別間。</span>
          <button type="button" class="db-btn db-btn--sm" @click="handleCadRoomSelected(pendingRoom)">繼續編輯</button>
          <button type="button" class="db-btn db-btn--ghost db-btn--sm" @click="onAbandon" @blur="confirmingAbandon = false">
            {{ confirmingAbandon ? '確定放棄？進度會清除' : '放棄這間，改選其他' }}
          </button>
        </div>

        <!-- 設定過期時整塊停用（inert），免得在舊的平面圖上開始設計 -->
        <div class="plan-body" :class="{ 'is-refreshing': refreshing }" :inert="dirty">
          <RoomPickerCad
            :show-hint="false"
            :svg-markup="cadPlanResult.svg_markup || ''"
            :rooms="rooms"
            @select-room="handleCadRoomSelected"
          />
          <ul class="room-chips" aria-label="房間清單">
            <li v-for="r in rooms" :key="r.id">
              <button
                type="button" class="room-chip" :class="`is-${chipState(r)}`"
                @click="handleCadRoomSelected(r)"
              >
                <span class="chip-name">{{ r.label_zh }}</span>
                <span class="chip-area">{{ Math.round(r.actual_area_m2 || 0) }} m²</span>
                <span v-if="STATE_TEXT[chipState(r)]" class="chip-state">{{ chipState(r) === 'done' ? '✓ ' : '' }}{{ STATE_TEXT[chipState(r)] }}</span>
                <span v-else-if="r.id === suggestedId" class="chip-state chip-state--hint">建議先做</span>
              </button>
            </li>
          </ul>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.room-program-step {
  display: grid;
  grid-template-columns: minmax(300px, 340px) minmax(0, 1fr);
  gap: clamp(1.25rem, 3vw, 2.5rem);
  align-items: start;
}
.room-program-step.is-uploaded { grid-template-columns: minmax(0, 1fr); }
.plan-warn { color: var(--db-danger, #b3261e); }

/* ── 左：設定。桌機固定在畫面上，往下捲平面圖時還看得到 ── */
.setup {
  position: sticky;
  top: 16px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.1rem 1.1rem 1.25rem;
  border-radius: var(--db-radius-card);
  background: var(--db-chip-soft);
}
.setup-head { display: flex; flex-direction: column; gap: 0.7rem; }
.setup-title {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.35rem;
}

/* 單間／整層房屋：放在標題下面，一眼看出這是可以切換的模式 */
.mode-toggle {
  display: flex;
  padding: 4px;
  border: 1px solid #e2ddd0;
  border-radius: var(--db-radius-pill);
  background: #fff;
}
.mode-toggle button {
  flex: 1;
  padding: 0.5rem 0.8rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-display);
  font-weight: 500;
  font-size: 0.95rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.mode-toggle button:not(.active):hover { background: var(--db-chip-soft); color: var(--db-text); }
.mode-toggle button:disabled { opacity: 0.5; cursor: not-allowed; }
.mode-toggle button.active { background: var(--db-accent); color: var(--db-on-accent); cursor: default; }

.setup-body { display: flex; flex-direction: column; gap: 1rem; }

.size-block { display: flex; flex-direction: column; gap: 0.6rem; }
.ping-row, .dim-fields { display: flex; align-items: center; flex-wrap: wrap; gap: 0.4rem 0.45rem; }
.size-label { font-size: 0.88rem; color: var(--db-text-soft); }
.size-input { width: 68px; height: 36px; padding: 0 0.3rem; text-align: center; font-size: 1rem; font-variant-numeric: tabular-nums; }
.size-unit { font-size: 0.88rem; color: var(--db-text-soft); }
.dim-x { color: var(--db-placeholder); }
.ping-suffix { font-size: 0.82rem; color: var(--db-placeholder); white-space: nowrap; }
.size-hint, .size-error { margin: 0; font-size: 0.76rem; line-height: 1.5; color: var(--db-placeholder); }
.size-error { color: var(--db-danger); }

/* 房間數量：一列一種，小縮圖＋名稱＋步進器。0 間的整列變淡 */
.count-list { display: flex; flex-direction: column; gap: 0.4rem; margin: 0; padding: 0; list-style: none; }
.count-row {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.35rem 0.5rem 0.35rem 0.35rem;
  border-radius: var(--db-radius-chip);
  background: #fff;
  transition: opacity 0.16s;
}
.count-row.is-zero { opacity: 0.55; }
.count-row.is-zero:hover, .count-row.is-zero:focus-within { opacity: 1; }
.count-thumb {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 52px;
  height: 40px;
  overflow: hidden;
  border-radius: 8px;
  background: var(--db-chip);
  color: var(--db-text-soft);
  font-size: 1.4rem;
}
.count-thumb img { width: 100%; height: 100%; object-fit: cover; }
.count-row.is-zero .count-thumb img { filter: grayscale(0.85); }
.count-thumb--text { font-size: 1.1rem; }
.count-name { flex: 1; font-family: var(--db-font-display); font-size: 1rem; }
.count-stepper { display: inline-flex; align-items: center; gap: 0.15rem; }
.count-btn {
  width: 36px; height: 36px;
  border: none; border-radius: 50%;
  background: var(--db-chip-soft);
  color: var(--db-text);
  font-size: 1.1rem;
  line-height: 1;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.count-btn:hover { background: var(--db-accent); color: var(--db-on-accent); }
.count-btn:focus-visible { outline: 3px solid var(--db-accent); outline-offset: 2px; }
.count-num { min-width: 1.6em; text-align: center; font-family: var(--db-font-num); font-variant-numeric: tabular-nums; font-size: 1.2rem; }

.extra-remove { width: 32px; height: 32px; border: none; border-radius: 50%; background: var(--db-chip-soft); cursor: pointer; }
.extra-remove:hover { background: var(--db-chip); }
.count-row--add { padding: 0.35rem; gap: 0.5rem; }
.add-input { flex: 1; min-width: 0; height: 36px; }
.add-row {
  width: 100%;
  min-height: 44px;
  border: 2px dashed #c9c4bb;
  border-radius: var(--db-radius-chip);
  background: none;
  color: var(--db-text-soft);
  font-size: 0.92rem;
  cursor: pointer;
}
.add-row:hover { border-color: var(--db-accent-deep); color: var(--db-text); background: #fff; }

.generate-btn { width: 100%; min-height: 46px; }
.live-note { margin: 0; font-size: 0.8rem; line-height: 1.5; color: var(--db-text-soft); }
.live-error { color: var(--db-danger); }
/* 已有設計師平面圖的入口：有邊框、有圖示的次要按鈕，放在平面圖標題列右側，才找得到 */
.upload-btn {
  display: inline-flex; align-items: center; gap: 0.5rem;
  min-height: 44px; padding: 0.5rem 1.1rem;
  border: 1.5px solid var(--db-accent-ink); border-radius: var(--db-radius-pill);
  background: #fff; color: var(--db-accent-ink);
  font-size: 0.92rem; font-weight: 600; cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.upload-btn:hover:not(:disabled) { background: var(--db-accent-ink); color: #fff; }
.upload-btn:focus-visible { outline: 3px solid var(--db-accent); outline-offset: 2px; }
.upload-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.plan-body.is-refreshing { opacity: 0.55; }

/* 窄螢幕生成後收起來的一行摘要 */
.setup-summary {
  display: flex; align-items: center; justify-content: space-between; gap: 0.8rem;
  width: 100%; min-height: 44px; padding: 0.5rem 0.9rem;
  border: 1px solid #e2ddd0; border-radius: var(--db-radius-chip);
  background: #fff; color: var(--db-text); text-align: left; cursor: pointer;
}
.summary-text { font-size: 0.88rem; }
.summary-edit { flex-shrink: 0; font-size: 0.82rem; color: var(--db-text-soft); text-decoration: underline; }

/* ── 右：平面圖 ── */
.plan-pane { min-width: 0; display: flex; flex-direction: column; gap: 0.9rem; }
.plan-head { display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem 1.25rem; }
.plan-head-text { display: flex; flex-direction: column; gap: 0.25rem; min-width: 0; }
.plan-title { margin: 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: 1.45rem; }
.plan-sub { margin: 0; font-size: 0.92rem; color: var(--db-text-soft); }

.plan-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 210px;   /* 寬螢幕：平面圖＋右邊一欄房間清單，橫向空間才用得完 */
  gap: 1.25rem;
  align-items: start;
  transition: opacity 0.2s, filter 0.2s;
}
.plan-pane.is-stale .plan-body { opacity: 0.4; filter: grayscale(0.6); }
.stale-banner {
  display: flex; align-items: center; justify-content: space-between; gap: 0.8rem;
  padding: 0.65rem 0.9rem; border-radius: var(--db-radius-chip);
  background: var(--db-danger-soft); color: var(--db-danger); font-size: 0.88rem;
}
.link-btn { padding: 0.2rem 0; border: none; background: none; color: inherit; font-size: 0.88rem; font-weight: 600; text-decoration: underline; cursor: pointer; }

/* 房間標籤：名稱＋面積＋狀態。是平面圖的文字版入口 */
.room-chips { display: flex; flex-direction: column; gap: 0.5rem; margin: 0; padding: 0; list-style: none; }
.room-chip {
  display: flex; align-items: baseline; gap: 0.5rem; width: 100%;
  min-height: 44px; padding: 0.5rem 0.95rem;
  border: 1px solid #dcdcdc; border-radius: var(--db-radius-chip);
  background: #fff; color: var(--db-text); cursor: pointer;
  transition: border-color 0.16s, background 0.16s;
}
.room-chip:hover { border-color: var(--db-accent-deep); background: #f7f6f3; }
.room-chip:focus-visible { outline: 3px solid var(--db-accent); outline-offset: 2px; }
.chip-name { font-family: var(--db-font-display); font-size: 0.98rem; }
.chip-state { margin-left: auto; }
.chip-area { font-size: 0.78rem; color: var(--db-text-soft); font-variant-numeric: tabular-nums; }
.chip-state { font-size: 0.74rem; color: var(--db-text-soft); }
.chip-state--hint { color: var(--db-accent-ink); font-weight: 600; }
.room-chip.is-done { border-color: var(--db-accent-ink); background: var(--db-accent-soft); }
.room-chip.is-done .chip-state { color: var(--db-accent-ink); font-weight: 600; }
.room-chip.is-active { border-color: var(--db-text); border-style: dashed; }
.room-chip.is-rendering { border-style: dashed; border-color: var(--db-accent-ink); background: var(--db-accent-soft); }

.pending-bar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem;
  padding: 0.7rem 1rem; border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft); font-size: 0.9rem;
}
.pending-text { flex: 1 1 14rem; color: var(--db-text); }

/* 還沒有平面圖 */
.plan-empty {
  display: flex; flex-direction: column; align-items: center; gap: 0.9rem;
  padding: clamp(1.5rem, 4vw, 3rem) 1.5rem;
  border: 2px dashed #d9d6cf; border-radius: var(--db-radius-card);
  color: var(--db-text-soft); text-align: center;
}
.empty-glyph { width: 120px; color: #cfcac1; }
.empty-title { margin: 0; font-family: var(--db-font-display); font-style: italic; font-size: 1.3rem; color: var(--db-text); }
.empty-sub, .empty-error { margin: 0; font-size: 0.92rem; }
.empty-error { color: var(--db-danger); }
@media (prefers-reduced-motion: reduce) {
  .plan-body { transition: none; }
}

/* 平面圖右邊放不下清單時，清單改放平面圖下面，排成一列 */
@media (max-width: 1280px) {
  .plan-body { grid-template-columns: minmax(0, 1fr); }
  .room-chips { flex-direction: row; flex-wrap: wrap; }
  .room-chip { width: auto; border-radius: var(--db-radius-pill); }
  .chip-state { margin-left: 0; }
}

/* 窄螢幕：上下堆疊，設定不再固定 */
@media (max-width: 960px) {
  .room-program-step { grid-template-columns: minmax(0, 1fr); }
  .setup { position: static; }
}
</style>
