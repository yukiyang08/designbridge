<script setup>
/**
 * 風水／動線示範：同一間臥室，切換「排版前 / 自動調整後」。
 * 前：門直沖床（紅）；後：床移開並留出門到窗的動線。資料為手寫範例，不呼叫後端。
 */
import { ref, computed } from 'vue'
import FengshuiMiniPlan from '@/components/FengshuiMiniPlan.vue'

const fixed = ref(false)

const doors = [{ wall: 'near', x: 0.08, y: 0, w: 0.2, h: 0 }]
const windows = [{ wall: 'far', x: 0.4, y: 0, w: 0.3, h: 0 }]
const wardrobe = { id: 'wardrobe_1', type: 'wardrobe', x: 0.78, y: 0.72, w: 0.2, h: 0.2 }
const nightstand = { id: 'nightstand_1', type: 'nightstand', x: 0.5, y: 0.08, w: 0.1, h: 0.12 }

const BEFORE = {
  room_w: 4, room_d: 3.6, doors, windows,
  placements: [{ id: 'bed_1', type: 'bed', x: 0.05, y: 0.12, w: 0.4, h: 0.55 }, wardrobe, nightstand],
}
const AFTER = {
  ...BEFORE,
  placements: [{ id: 'bed_1', type: 'bed', x: 0.58, y: 0.12, w: 0.4, h: 0.55 }, wardrobe, { ...nightstand, x: 0.46 }],
}

const plan = computed(() => (fixed.value ? AFTER : BEFORE))
const ghosts = computed(() => (fixed.value ? [BEFORE.placements[0]] : []))
const CHECKS = computed(() => [
  { t: '門不直沖床', ok: fixed.value },
  { t: '門到窗動線順暢', ok: fixed.value },
  { t: '衣櫃不擋通道', ok: true },
])
</script>

<template>
  <section class="fs" aria-labelledby="fs-h">
    <header class="head">
      <p class="eyebrow">風水與動線</p>
      <h2 id="fs-h">常見禁忌，排版時就先避開</h2>
      <p class="lead">門沖床、鏡照床、動線被擋住……排版後自動檢查，違規的家具會標紅並移到合適的位置。</p>
    </header>

    <div class="tabs" role="group" aria-label="切換排版前後">
      <button type="button" :aria-pressed="!fixed" @click="fixed = false">排版前</button>
      <button type="button" :aria-pressed="fixed" @click="fixed = true">自動調整後</button>
    </div>

    <div class="body">
      <FengshuiMiniPlan
        class="plan"
        :plan="plan"
        :offenders="fixed ? [] : ['bed_1', 'door']"
        :moved="fixed ? ['bed_1'] : []"
        :ghosts="ghosts"
        title="臥室 4.0 × 3.6 m"
      />
      <ul class="checks" aria-label="檢查結果（範例）">
        <li v-for="c in CHECKS" :key="c.t" :class="c.ok ? 'ok' : 'bad'">
          <b>{{ c.ok ? '✓' : '✕' }}</b>{{ c.t }}
        </li>
        <li class="msg" role="status">{{ fixed ? '床已移到門的斜對側，進門不直視床腳。' : '進門視線直沖床腳，風水上稱「門沖床」。' }}</li>
      </ul>
    </div>
    <p class="note">示範：手繪範例，實際結果依你的房型與家具而定。</p>
  </section>
</template>

<style scoped>
.fs { width: min(1000px, calc(100vw - 3rem)); margin: 0 auto; padding: clamp(2rem, 5vw, 4rem) 0; }
.head { text-align: center; margin-bottom: 1.5rem; }
.eyebrow { margin: 0 0 0.6rem; font-size: 0.82rem; letter-spacing: 0.14em; color: var(--db-accent-ink); }
h2 { margin: 0 0 0.9rem; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: clamp(1.7rem, 3.2vw, 2.5rem); line-height: 1.35; text-wrap: balance; color: var(--db-text); }
.lead { max-width: 36rem; margin: 0 auto; line-height: 1.85; color: var(--db-text-soft); }

.tabs { display: flex; justify-content: center; gap: 0.5rem; margin-bottom: 1.2rem; }
.tabs button { padding: 0.4rem 1.2rem; border: 1px solid var(--db-text-soft); border-radius: var(--db-radius-pill); background: none; font: inherit; font-size: 0.9rem; color: var(--db-text); cursor: pointer; }
.tabs button[aria-pressed='true'] { background: var(--db-text); color: #fff; }

.body { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: clamp(1rem, 3vw, 2.5rem); align-items: center; }
.plan { padding: 0.8rem; background: #fff; border-radius: var(--db-radius-card); box-shadow: var(--db-shadow-card); }
.checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.7rem; }
.checks li { display: flex; align-items: center; gap: 0.6rem; color: var(--db-text); }
.checks b { display: grid; place-items: center; width: 1.5rem; height: 1.5rem; border-radius: 50%; color: #fff; font-size: 0.8rem; transition: background 0.3s; }
.ok b { background: var(--db-ok); }
.bad b { background: var(--db-danger); }
.msg { margin-top: 0.4rem; padding: 0.7rem 0.9rem; border-left: 2px solid var(--db-accent-ink); background: var(--db-accent-soft); font-size: 0.9rem; line-height: 1.7; color: var(--db-text-soft); }
.note { margin: 0.8rem 0 0; text-align: center; font-size: 0.8rem; color: var(--db-text-soft); }

@media (max-width: 760px) {
  .body { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .checks b { transition: none; }
}
</style>
