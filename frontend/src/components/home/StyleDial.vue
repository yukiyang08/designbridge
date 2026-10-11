<script setup>
/**
 * 同一個房間換風格：圖片疊放交叉淡入，晶片切換。
 * 自動輪播符合無障礙規則：有暫停鍵、滑入／聚焦就停、離開畫面就停、減少動態時預設不播；
 * 使用者手動點選後也視為接管，不再自動切。
 */
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { prefersReducedMotion } from '@/composables/useScrollProgress'
import modern from '@/assets/home/modern.jpg'
import industrial from '@/assets/home/industrial.jpg'
import luxury from '@/assets/home/luxury.jpg'
import country from '@/assets/home/country.jpg'

const STYLES = [
  { id: 'modern', name: '現代', img: modern },
  { id: 'industrial', name: '工業', img: industrial },
  { id: 'luxury', name: '奢華', img: luxury },
  { id: 'country', name: '鄉村', img: country },
]
const INTERVAL = 3800

const idx = ref(0)
const playing = ref(!prefersReducedMotion())
const hovering = ref(false)
const visible = ref(false)
const announce = ref('')
const root = ref(null)
let timer = 0
let io

function sync() {
  clearInterval(timer)
  if (playing.value && !hovering.value && visible.value) {
    timer = setInterval(() => { idx.value = (idx.value + 1) % STYLES.length }, INTERVAL)
  }
}
watch([playing, hovering, visible], sync)

function pick(i) {
  idx.value = i
  playing.value = false
  announce.value = `已切換為${STYLES[i].name}風格`
}

onMounted(() => {
  io = new IntersectionObserver(([e]) => { visible.value = e.isIntersecting }, { threshold: 0.35 })
  io.observe(root.value)
})
onBeforeUnmount(() => { clearInterval(timer); io?.disconnect() })
</script>

<template>
  <section
    ref="root"
    class="dial"
    aria-labelledby="dial-h"
    @mouseenter="hovering = true"
    @mouseleave="hovering = false"
    @focusin="hovering = true"
    @focusout="hovering = false"
  >
    <div class="copy">
      <p class="eyebrow">一鍵換風格</p>
      <h2 id="dial-h">同一個房間，<br />換個風格就是另一個家</h2>
      <p class="lead">
        色調、材質、燈具一起換。不滿意可以立刻切回，已生成過的風格也會留著，不必重等。
      </p>
    </div>

    <div class="demo">
      <div class="frame">
        <img
          v-for="(s, i) in STYLES"
          :key="s.id"
          :src="s.img"
          :alt="i === idx ? `${s.name}風格的客廳生成圖` : ''"
          :aria-hidden="i === idx ? undefined : 'true'"
          :class="{ on: i === idx }"
          loading="lazy"
        />
        <span class="badge" aria-hidden="true">{{ STYLES[idx].name }}</span>
      </div>

      <div class="controls">
        <div class="chips" role="group" aria-label="選擇風格">
          <button
            v-for="(s, i) in STYLES"
            :key="s.id"
            type="button"
            class="chip"
            :aria-pressed="i === idx"
            @click="pick(i)"
          >{{ s.name }}</button>
        </div>
        <button
          type="button"
          class="play"
          :aria-pressed="playing"
          :aria-label="playing ? '暫停自動切換' : '播放自動切換'"
          @click="playing = !playing"
        >
          <svg v-if="playing" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5l12 7-12 7z" /></svg>
        </button>
      </div>

      <p class="sr-only" aria-live="polite">{{ announce }}</p>
      <p class="note">示範：同一個房間以一鍵換風格生成 4 種風格（系統共 8 種）。每次由 AI 重新生成，家具擺放與視角可能略有不同。</p>
    </div>
  </section>
</template>

<style scoped>
.dial {
  display: grid;
  grid-template-columns: minmax(0, 4fr) minmax(0, 7fr);
  align-items: center;
  gap: clamp(1.5rem, 5vw, 4rem);
  width: min(1180px, calc(100vw - 3rem));
  margin: 0 auto;
  padding: clamp(3.5rem, 8vw, 7rem) 0;
}
.eyebrow { margin: 0 0 0.6rem; font-size: 0.82rem; letter-spacing: 0.18em; color: var(--db-accent-ink); }
h2 {
  margin: 0 0 1rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.9rem, 3.4vw, 2.7rem);
  line-height: 1.3;
  text-wrap: balance;
  color: var(--db-text);
}
.lead { margin: 0; max-width: 26rem; line-height: 1.85; color: var(--db-text-soft); }

.frame {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: var(--db-radius-card);
  overflow: hidden;
  background: var(--db-accent-soft);
  box-shadow: var(--db-shadow-card);
}
.frame img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  transform: scale(1.035);
  transition: opacity 0.9s ease, transform 1.6s ease;
}
.frame img.on { opacity: 1; transform: scale(1); }
.badge {
  position: absolute;
  left: 1rem;
  bottom: 1rem;
  padding: 0.3rem 0.9rem;
  border-radius: var(--db-radius-pill);
  background: rgba(20, 18, 14, 0.62);
  color: #fff;
  font-family: var(--db-font-display);
  font-size: 1rem;
  backdrop-filter: blur(6px);
}

.controls { display: flex; align-items: center; gap: 0.75rem; margin-top: 1rem; }
.chips { display: flex; flex-wrap: wrap; gap: 0.5rem; flex: 1; }
.chip {
  min-height: 44px;
  padding: 0 1.2rem;
  border: 1.5px solid var(--db-accent);
  border-radius: var(--db-radius-pill);
  background: transparent;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.18s, color 0.18s;
}
.chip:hover { background: var(--db-accent-soft); }
.chip[aria-pressed='true'] { background: var(--db-accent); color: var(--db-on-accent); }
.play {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 1.5px solid var(--db-accent);
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
}
.play svg { width: 18px; height: 18px; fill: var(--db-accent-ink); }
.play:hover { background: var(--db-accent-soft); }
.chip:focus-visible, .play:focus-visible { outline: 3px solid var(--db-accent-ink); outline-offset: 2px; }

.note { margin: 0.9rem 0 0; font-size: 0.82rem; line-height: 1.7; color: var(--db-text-soft); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

@media (max-width: 860px) {
  .dial { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .frame img { transition: opacity 0.2s; transform: none; }
}
</style>
