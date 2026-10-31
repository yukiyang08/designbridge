<script setup>
/**
 * 風水＋動線健檢報告卡。
 *
 * 風水關閉時只給一行提示（有幾處不符合＋一鍵套用），不在意風水的人不會被打擾；
 * 開啟時列出分數、違規項目（哪件家具、為什麼、化解法）與動線問題。
 */
import { computed } from 'vue'
import { furnitureLabel } from '@/config/furniture'
import FengshuiMiniPlan from '@/components/FengshuiMiniPlan.vue'

const props = defineProps({
  report: { type: Object, default: null },        // /api/fengshui/audit 的回應
  placements: { type: Array, default: () => [] }, // 用來把違規家具的 id 換成名稱
  enabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  /** 可以一鍵調整家具（平面圖步驟）；照片健檢只能給建議 */
  fixable: { type: Boolean, default: false },
  lastFix: { type: Object, default: null },
  /** 關閉狀態下按鈕的文字（照片健檢是「下一步生成時套用」，不是當場調整） */
  enableLabel: { type: String, default: '套用風水建議並調整' },
  /** 標題列放開關：整層／上傳平面圖流程沒有空間設定頁，這裡是唯一的開關 */
  toggleable: { type: Boolean, default: false },
  /** 給了房間尺寸才畫小平面圖（編輯器上沒畫門窗時，靠它看出規則在對什麼） */
  roomW: { type: Number, default: 0 },
  roomD: { type: Number, default: 0 },
})
defineEmits(['fix', 'undo', 'enable', 'toggle'])

const fs = computed(() => props.report?.fengshui || null)
const circ = computed(() => props.report?.circulation || null)
const failed = computed(() => (fs.value?.rules || []).filter(r => r.status === 'fail'))
const passed = computed(() => (fs.value?.rules || []).filter(r => r.status === 'pass'))
const circIssues = computed(() => circ.value?.issues || [])

const nameOf = computed(() => {
  const m = { door: '門' }
  for (const p of props.placements) m[p.id] = furnitureLabel(p.type)
  return m
})
const names = ids => [...new Set(ids.map(id => nameOf.value[id] || id))].join('、')

const currentOffenders = computed(() => [
  ...failed.value.flatMap(r => r.offenders),
  ...circIssues.value.flatMap(i => i.offenders),
])
const planOf = placements => ({
  room_w: props.roomW,
  room_d: props.roomD,
  placements,
  doors: (props.report?.doors || []).map(d => ({ ...d, assumed: props.report.assumed_openings })),
  windows: props.report?.windows || [],
})
const showCompare = computed(() => props.roomW > 0 && !!props.lastFix?.moved)
// 編輯器上沒有門窗（沒有門窗資料的流程）時，報告自己畫一張，不然「開門不見床」對著哪扇門看不出來
const showPlan = computed(() => props.roomW > 0 && !showCompare.value && !!props.report?.assumed_openings)

const scoreTone = s => s == null ? '' : s >= 85 ? 'is-good' : s >= 60 ? 'is-mid' : 'is-bad'
</script>

<template>
  <section v-if="report" class="fs-report" :class="{ 'is-loading': loading }" aria-live="polite">
    <header class="rp-head">
      <h3 class="rp-title">風水＋動線健檢</h3>
      <span v-if="loading" class="rp-loading">更新中…</span>
      <label v-if="toggleable" class="rp-switch">
        <span>套用風水建議</span>
        <input type="checkbox" role="switch" :checked="enabled" @change="$emit('toggle', $event.target.checked)" />
        <span class="rp-switch-track" aria-hidden="true"><span class="rp-switch-thumb" /></span>
      </label>
    </header>

    <!-- ── 風水關閉：只給一行提示 ── -->
    <div v-if="!enabled" class="rp-off">
      <p v-if="failed.length">
        這個配置有 <strong>{{ failed.length }}</strong> 處不符合風水
        <span class="rp-off-list">（{{ failed.map(r => r.label).join('、') }}）</span>
      </p>
      <p v-else-if="fs?.score != null" class="rp-ok">✓ 目前的擺法都符合風水</p>
      <button v-if="failed.length" type="button" class="db-btn db-btn--ghost db-btn--sm" @click="$emit('enable')">
        {{ enableLabel }}
      </button>
    </div>

    <!-- ── 風水開啟：完整報告 ── -->
    <template v-else>
      <div class="rp-scores">
        <!-- 沒有可評的規則／沒有門時不顯示，避免看起來像壞掉或誤判滿分 -->
        <div v-if="fs?.score != null" class="rp-score" :class="scoreTone(fs.score)">
          <span class="rp-score-num">{{ fs.score }}</span>
          <span class="rp-score-label">風水分數</span>
        </div>
        <div v-if="circ?.score != null" class="rp-score" :class="scoreTone(circ.score)">
          <span class="rp-score-num">{{ circ.score }}</span>
          <span class="rp-score-label">動線分數</span>
        </div>
        <div class="rp-actions">
          <p v-if="lastFix?.moved" class="rp-fixed">
            已調整 {{ lastFix.moved }} 件家具
            <button type="button" class="rp-link" @click="$emit('undo')">復原</button>
          </p>
          <p v-else-if="lastFix && failed.length" class="rp-fixed">空間不夠，無法自動避開，請參考化解建議</p>
          <button
            v-else-if="fixable && failed.length"
            type="button" class="db-btn db-btn--sm" :disabled="loading" @click="$emit('fix')"
          >依風水自動調整家具</button>
        </div>
      </div>

      <template v-if="showCompare">
        <div class="rp-plans">
          <FengshuiMiniPlan title="調整前" :plan="planOf(lastFix.previous)" :offenders="lastFix.beforeOffenders" />
          <FengshuiMiniPlan
            title="調整後" :plan="planOf(placements)" :offenders="currentOffenders"
            :moved="lastFix.movedIds" :ghosts="lastFix.previous.filter(p => lastFix.movedIds.includes(p.id))"
          />
        </div>
        <ul class="rp-changes">
          <li v-for="(m, k) in lastFix.moves" :key="k"><strong>{{ m.label }}</strong>{{ m.text }}</li>
        </ul>
        <p v-if="lastFix.resolved.length" class="rp-resolved">✓ 已解決：{{ lastFix.resolved.join('、') }}</p>
      </template>
      <div v-else-if="showPlan" class="rp-plans rp-plans--single">
        <FengshuiMiniPlan title="門窗位置（推估）與違規家具" :plan="planOf(placements)" :offenders="currentOffenders" />
      </div>

      <!-- 問題多時預設收合，首屏只看分數；只有 1 項時直接展開 -->
      <details class="rp-more" :open="failed.length <= 1">
        <summary>詳細說明<template v-if="failed.length">（{{ failed.length }} 項待改善）</template></summary>
      <ul v-if="failed.length" class="rp-list">
        <li v-for="r in failed" :key="r.trigger" class="rp-item is-fail">
          <p class="rp-item-head">
            <span class="rp-mark" aria-hidden="true">⚠</span>
            <strong>{{ r.label }}</strong>
            <span v-if="r.offenders.length" class="rp-who">{{ names(r.offenders) }}</span>
          </p>
          <p class="rp-reason">{{ r.reason }}</p>
          <p class="rp-remedy">
            <span>{{ lastFix ? '無法自動避開，建議' : '化解' }}：</span>{{ r.remedy }}
          </p>
        </li>
      </ul>
      <p v-else-if="fs?.score != null" class="rp-ok">✓ 套用的風水規則全部符合</p>

      <p v-if="passed.length" class="rp-passed">
        已符合：{{ passed.map(r => r.label).join('、') }}
      </p>
      </details>
    </template>

    <!-- 動線問題不論風水開關都顯示：擋門、走不到是實際的使用問題 -->
    <ul v-if="circIssues.length" class="rp-list">
      <li v-for="(i, k) in circIssues" :key="k" class="rp-item is-circ">
        <p class="rp-item-head">
          <span class="rp-mark" aria-hidden="true">↯</span>
          <strong>{{ i.kind === 'door_blocked' ? '門口被擋住' : '有家具走不到' }}</strong>
          <span class="rp-who">{{ names(i.offenders) }}</span>
        </p>
        <p class="rp-reason">{{ i.message }}</p>
        <p class="rp-remedy"><span>建議：</span>{{ i.remedy }}</p>
      </li>
    </ul>

    <p v-if="report.assumed_openings" class="rp-note">
      這個房間沒有門窗資料，以「門在下方牆中央、窗在上方牆中央」估算。
    </p>
  </section>
</template>

<style scoped>
.fs-report {
  margin-top: 1.25rem;
  padding: 1.1rem 1.25rem;
  border: 1px solid #e6e2d8;
  border-radius: var(--db-radius-chip);
  background: #fff;
  transition: opacity 0.16s;
}
.fs-report.is-loading { opacity: 0.7; }

.rp-head { display: flex; align-items: baseline; gap: 0.75rem; }
.rp-title { margin: 0; font-family: var(--db-font-display); font-size: 1.1rem; font-weight: 600; }
.rp-loading { color: var(--db-text-soft); font-size: 0.8rem; }
.rp-switch { display: flex; align-items: center; gap: 0.5rem; margin-left: auto; font-size: 0.85rem; cursor: pointer; }
.rp-switch input { position: absolute; opacity: 0; pointer-events: none; }
.rp-switch-track {
  position: relative; width: 40px; height: 22px; border-radius: var(--db-radius-pill);
  background: var(--db-chip); transition: background 0.16s;
}
.rp-switch-thumb {
  position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%;
  background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25); transition: transform 0.16s;
}
.rp-switch input:checked + .rp-switch-track { background: var(--db-ink); }
.rp-switch input:checked + .rp-switch-track .rp-switch-thumb { transform: translateX(18px); }
.rp-switch input:focus-visible + .rp-switch-track { outline: 2px solid var(--db-accent-ink); outline-offset: 2px; }

.rp-off { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.6rem 1rem; margin-top: 0.6rem; }
.rp-off p { margin: 0; font-size: 0.92rem; }
.rp-off-list { color: var(--db-text-soft); font-size: 0.85rem; }

.rp-more { margin-top: 0.6rem; }
.rp-more > summary { cursor: pointer; font-size: 0.88rem; color: var(--db-text-soft); }
.rp-scores { display: flex; flex-wrap: wrap; align-items: center; gap: 1.5rem; margin-top: 0.8rem; }
.rp-score { display: flex; flex-direction: column; align-items: center; min-width: 4.5rem; }
.rp-score-num { font-family: var(--db-font-num); font-size: 1.9rem; line-height: 1.1; }
.rp-score-label { color: var(--db-text-soft); font-size: 0.78rem; }
.rp-score.is-good .rp-score-num { color: var(--db-ok); }
.rp-score.is-mid .rp-score-num { color: var(--db-accent-ink); }
.rp-score.is-bad .rp-score-num { color: var(--db-danger); }
.rp-actions { margin-left: auto; }
.rp-fixed { margin: 0; font-size: 0.88rem; }
.rp-link {
  margin-left: 0.4rem;
  border: none;
  background: none;
  padding: 0;
  color: var(--db-text);
  font: inherit;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

.rp-list { display: flex; flex-direction: column; gap: 0.6rem; margin: 0.9rem 0 0; padding: 0; list-style: none; }
.rp-item { padding: 0.7rem 0.85rem; border-radius: 8px; }
.rp-item.is-fail { background: var(--db-danger-soft); }
.rp-item.is-circ { background: var(--db-chip-soft); }
.rp-item p { margin: 0; }
.rp-item-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.45rem; font-size: 0.95rem; }
.rp-mark { color: var(--db-danger); }
.is-circ .rp-mark { color: var(--db-text-soft); }
.rp-who { color: var(--db-text-soft); font-size: 0.82rem; }
.rp-reason { margin-top: 0.25rem !important; color: var(--db-text-soft); font-size: 0.83rem; line-height: 1.55; }
.rp-remedy { margin-top: 0.25rem !important; font-size: 0.83rem; line-height: 1.55; }
.rp-remedy span { font-weight: 600; }

.rp-plans { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1rem; }
.rp-plans--single { grid-template-columns: minmax(0, 360px); }
.rp-plans :deep(svg) { max-height: 220px; }
.rp-changes { display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; margin: 0.8rem 0 0; padding: 0; list-style: none; font-size: 0.88rem; }
.rp-changes strong { margin-right: 0.4rem; color: var(--db-ok); }
.rp-resolved { margin: 0.5rem 0 0; color: var(--db-ok); font-size: 0.88rem; }

.rp-ok { margin: 0.8rem 0 0; color: var(--db-ok); font-size: 0.9rem; }
.rp-passed { margin: 0.8rem 0 0; color: var(--db-text-soft); font-size: 0.82rem; line-height: 1.55; }
.rp-note { margin: 0.8rem 0 0; color: var(--db-text-soft); font-size: 0.78rem; }

@media (max-width: 600px) {
  .rp-actions { margin-left: 0; width: 100%; }
  .rp-plans { grid-template-columns: 1fr; }
}
</style>
