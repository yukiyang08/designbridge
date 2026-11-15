<script setup>
/**
 * 首頁：Figma MacBook Air - 5 的標語＋開始設計，往下是功能介紹的捲動故事。
 * Hero 維持 Figma 原圖；下方打字示範只是「可以怎麼描述」的範例（滑入就停、減少動態時不播）。
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import AppNav from '@/components/shell/AppNav.vue'
import StoryPlan from '@/components/home/StoryPlan.vue'
import PlanPrecision from '@/components/home/PlanPrecision.vue'
import FengshuiDemo from '@/components/home/FengshuiDemo.vue'
import CompareSlider from '@/components/home/CompareSlider.vue'
import StyleDial from '@/components/home/StyleDial.vue'
import StyleDeck from '@/components/home/StyleDeck.vue'
import QuoteReceipt from '@/components/home/QuoteReceipt.vue'
import { prefersReducedMotion } from '@/composables/useScrollProgress'
import heroBg from '@/assets/figma/room-bg.png'
import panoCrop from '@/assets/home/pano-crop.jpg'
import thumbPlan from '@/assets/figma/entry-plan.png'
import thumbPhoto from '@/assets/figma/entry-photo.png'
import thumbScratch from '@/assets/figma/entry-scratch.png'

const router = useRouter()
const start = () => router.push('/start')

const PROMPTS = [
  { text: '木質感、採光充足的明亮感' },
  { text: '工業風挑高客廳，紅磚牆與黑色鋼構' },
  { text: '奢華、水晶吊燈、深色木飾板' },
]
const ENTRIES = [
  { img: thumbPlan, label: '平面圖', t: '先看懂格局，再想像每個房間' },
  { img: thumbPhoto, label: '現況照片', t: '從熟悉的空間，試出新的可能' },
  { img: thumbScratch, label: '靈感描述', t: '把腦中的畫面，慢慢具體化' },
]

/* ── 打字示範 ── */
const cur = ref(0)
const shown = ref(prefersReducedMotion() ? PROMPTS[0].text : '')
const playing = ref(!prefersReducedMotion())
const hovering = ref(false)
let t = 0

function stop() { clearTimeout(t) }
function run() {
  stop()
  if (!playing.value || hovering.value || document.hidden) return
  const full = PROMPTS[cur.value].text
  let i = 0
  shown.value = ''
  const type = () => {
    i++
    shown.value = full.slice(0, i)
    if (i < full.length) t = setTimeout(type, 70)
    else t = setTimeout(() => { cur.value = (cur.value + 1) % PROMPTS.length; run() }, 3200)
  }
  type()
}
function setHover(v) {
  hovering.value = v
  if (v) { stop(); shown.value = PROMPTS[cur.value].text } else run()
}
const onVis = () => (document.hidden ? stop() : run())
onMounted(() => { run(); document.addEventListener('visibilitychange', onVis) })
onBeforeUnmount(() => { stop(); document.removeEventListener('visibilitychange', onVis) })
const caretOn = computed(() => playing.value && !hovering.value)

/* ── 滑鼠景深：Hero 背景視差、入口卡片跟著游標傾斜（觸控與減少動態不啟用，位移交給 CSS 變數） ── */
const canTilt = (e) => e.pointerType === 'mouse' && !prefersReducedMotion()
function track(e, kx, ky) {
  if (!canTilt(e)) return
  const el = e.currentTarget, r = el.getBoundingClientRect()
  el.style.setProperty('--mx', (((e.clientX - r.left) / r.width - 0.5) * kx).toFixed(3))
  el.style.setProperty('--my', (((e.clientY - r.top) / r.height - 0.5) * ky).toFixed(3))
}
function untrack(e) {
  e.currentTarget.style.removeProperty('--mx')
  e.currentTarget.style.removeProperty('--my')
}
</script>

<template>
  <div class="home">
    <header class="hero" @pointermove="track($event, 2, 2)" @pointerleave="untrack">
      <div class="hero-bg" aria-hidden="true"><img :src="heroBg" alt="" /></div>
      <AppNav />

      <div class="hero-body">
        <h1 class="headline">
          <span>你的想像，</span>
          <span>我們幫你變成現實</span>
        </h1>

        <div class="demo" @mouseenter="setHover(true)" @mouseleave="setHover(false)" @focusin="setHover(true)" @focusout="setHover(false)">
          <p class="sr-only">範例：輸入一段描述，就能生成對應風格的房間。</p>
          <div class="demo-input" aria-hidden="true">
            <span class="demo-label">描述你理想中的空間…</span>
            <span class="typed">{{ shown }}<i :class="['caret', { blink: caretOn }]"></i></span>
          </div>
        </div>

        <button class="start-btn" type="button" @click="start">開始設計</button>
      </div>

      <a class="scroll-cue" href="#features" aria-label="往下看功能介紹">
        <span>看看能做什麼</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
      </a>
    </header>

    <main id="features">
      <section class="entries" aria-labelledby="entries-h">
        <h2 id="entries-h">讓設計，從你手邊的靈感開始</h2>
        <p class="entries-intro">一張平面圖、一張現況照，或一個還沒成形的念頭，都能成為新家的起點。</p>
        <ul>
          <li v-for="e in ENTRIES" :key="e.t">
            <button type="button" class="entry" @click="start" @pointermove="track($event, 12, -10)" @pointerleave="untrack">
              <span class="entry-img"><img :src="e.img" alt="" loading="lazy" /></span>
              <span class="entry-cap">
                <span class="entry-label">{{ e.label }}</span>
                <strong>{{ e.t }}</strong>
              </span>
            </button>
          </li>
        </ul>
      </section>

      <StoryPlan />
      <PlanPrecision />
      <FengshuiDemo />
      <CompareSlider />
      <StyleDial />
      <StyleDeck />

      <section class="duo" aria-label="更多功能">
        <article class="pano-card">
          <div class="pano" aria-hidden="true"><img :src="panoCrop" alt="" loading="lazy" /></div>
          <div class="duo-copy">
            <p class="eyebrow">360° 環景</p>
            <h2>生成後，站進房間裡看看</h2>
            <p>效果圖可以延伸成 360° 環景，用滑鼠或手指拖曳環顧四周。環景需要額外生成，約 30 到 60 秒。</p>
          </div>
        </article>
        <article class="quote-card">
          <div class="duo-copy">
            <p class="eyebrow">家具報價</p>
            <h2>設計完，順便算好預算</h2>
            <p>依你的家具清單比對商品，列出品項與合計。報價獨立於生圖，需要時才產生。</p>
          </div>
          <QuoteReceipt />
        </article>
      </section>

      <section class="cta" aria-labelledby="cta-h">
        <h2 id="cta-h">準備好了嗎？</h2>
        <p>從一句描述或一張照片開始，幾分鐘就能看到你的家。</p>
        <button class="start-btn" type="button" @click="start">開始設計</button>
      </section>
    </main>
  </div>
</template>

<style scoped>
.home { background: var(--db-paper); font-family: var(--db-font-body); color: var(--db-text); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.eyebrow { margin: 0 0 0.6rem; font-size: 0.82rem; letter-spacing: 0.18em; color: var(--db-accent-ink); }

/* ── Hero ── */
.hero {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--db-ink);
  overflow: hidden;
}
.hero-bg { position: absolute; inset: 0; }
/* 設計稿：照片 opacity 60% 疊在 #313131 上 */
.hero-bg img {
  position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0.6;
  /* 放大一點留出視差的位移空間；背景與標題反向移動做出前後景深 */
  transform: scale(1.05) translate(calc(var(--mx, 0) * -12px), calc(var(--my, 0) * -8px));
  transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1);
}
.hero-body { transform: translate(calc(var(--mx, 0) * 5px), calc(var(--my, 0) * 3px)); transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1); }
.hero > :not(.hero-bg) { position: relative; }

.hero-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  gap: 2.25rem;
  padding: 0 clamp(1.5rem, 7vw, 5.7rem) 6rem;
}
.headline {
  margin: 0;
  display: flex;
  flex-direction: column;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(2.25rem, 5vw, 4rem);
  line-height: 1.35;
  color: #fff;
  text-shadow: 0 2px 24px rgba(0, 0, 0, 0.4);
}

.demo {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: min(34rem, 100%);
}
.demo-input {
  flex: 1;
  min-width: 0;
  padding: 0.7rem 1.1rem;
  border: 1px solid rgba(255, 255, 255, 0.55);
  border-radius: var(--db-radius-chip);
  background: rgba(20, 18, 14, 0.42);
  backdrop-filter: blur(8px);
  color: #fff;
}
.demo-label { display: block; font-size: 0.74rem; letter-spacing: 0.14em; opacity: 0.85; }
.typed { display: block; min-height: 1.7em; margin-top: 0.15rem; font-size: 1.1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.caret { display: inline-block; width: 2px; height: 1.1em; margin-left: 2px; background: #fff; vertical-align: -0.15em; }
.caret.blink { animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }

.start-btn {
  min-width: 211px;
  padding: 0.85rem 2.5rem;
  border: none;
  border-radius: var(--db-radius-chip);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-family: var(--db-font-display);
  font-weight: 500;
  font-size: clamp(1.25rem, 2vw, 1.875rem);
  cursor: pointer;
  transition: background 0.18s, transform 0.14s, box-shadow 0.18s;
}
.start-btn:hover { background: var(--db-accent-deep); box-shadow: 0 10px 30px rgba(0, 0, 0, 0.32); transform: translateY(-2px); }
.start-btn:active { transform: translateY(0); }
.start-btn:focus-visible, .scroll-cue:focus-visible {
  outline: 3px solid #fff;
  outline-offset: 3px;
}

.scroll-cue {
  position: absolute !important;
  left: 50%;
  bottom: 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  color: #fff;
  font-size: 0.85rem;
  letter-spacing: 0.12em;
  text-decoration: none;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.5);
  transform: translateX(-50%);
}
.scroll-cue svg { width: 22px; height: 22px; animation: bob 1.8s ease-in-out infinite; }
@keyframes bob { 50% { transform: translateY(5px); } }

/* ── 三種開始方式 ── */
.entries {
  width: min(1180px, calc(100vw - 3rem));
  margin: 0 auto;
  padding: clamp(3.5rem, 8vw, 6rem) 0 clamp(2rem, 5vw, 4rem);
}
.entries h2, .duo h2, .cta h2 {
  margin: 0 0 1.5rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.7rem, 3vw, 2.4rem);
  line-height: 1.35;
  text-wrap: balance;
}
.entries h2 { margin-bottom: 0.65rem; }
.entries-intro { max-width: 55ch; margin: 0 0 2rem; color: var(--db-text-soft); line-height: 1.8; }
.entries ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: clamp(1rem, 2.4vw, 2rem); }
.entry {
  display: grid;
  gap: 0.85rem;
  width: 100%;
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
}
.entry { perspective: 800px; }
.entry-img {
  display: block; aspect-ratio: 16 / 10; border-radius: 12px; overflow: hidden; background: var(--db-accent-soft);
  transform: rotateY(calc(var(--mx, 0) * 1deg)) rotateX(calc(var(--my, 0) * 1deg));
  transition: transform 0.3s ease-out, box-shadow 0.3s;
}
.entry:hover .entry-img { box-shadow: 0 18px 40px rgba(49, 49, 49, 0.18); }
.entry-img img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform 0.4s; }
.entry:hover .entry-img img { transform: scale(1.04); }
.entry:hover strong { text-decoration: underline; text-underline-offset: 0.3em; }
.entry:focus-visible { outline: 3px solid var(--db-accent); outline-offset: 4px; border-radius: 12px; }
.entry-cap { display: grid; gap: 0.2rem; }
.entry-label { color: var(--db-accent-ink); font-size: 0.82rem; letter-spacing: 0.08em; }
.entry strong { font-family: var(--db-font-display); font-weight: 500; font-size: 1.2rem; line-height: 1.5; }

/* ── 更多功能 ── */
.duo {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: clamp(1.25rem, 3vw, 2.5rem);
  width: min(1180px, calc(100vw - 3rem));
  margin: 0 auto;
  padding: 0 0 clamp(3.5rem, 8vw, 6rem);
}
.duo article {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: clamp(1.25rem, 2.5vw, 2rem);
  border-radius: var(--db-radius-card);
  background: var(--db-card);
  box-shadow: var(--db-shadow-soft);
}
.duo-copy p:not(.eyebrow) { margin: 0; line-height: 1.85; color: var(--db-text-soft); }
.duo h2 { margin-bottom: 0.8rem; }
.pano { flex: 1; min-height: 220px; border-radius: 12px; overflow: hidden; background: var(--db-accent-soft); }
.pano img { display: block; height: 125%; width: auto; max-width: none; transform: translate(0, -8%); animation: pan 26s ease-in-out infinite alternate; }
@keyframes pan { from { transform: translate(0, -8%); } to { transform: translate(-18%, -8%); } }

/* ── 結尾 ── */
.cta {
  display: grid;
  justify-items: center;
  gap: 0.4rem;
  padding: clamp(3.5rem, 8vw, 6rem) 1.5rem;
  background: var(--db-ink);
  color: #fff;
  text-align: center;
}
.cta p { margin: 0 0 1.25rem; color: rgba(255, 255, 255, 0.82); }
.cta h2 { margin-bottom: 0.4rem; }

@media (max-width: 860px) {
  .entries ul, .duo { grid-template-columns: 1fr; }
  .pano { flex: none; min-height: 0; aspect-ratio: 16 / 9; }
  .hero-body { gap: 1.75rem; padding-bottom: 5rem; }
}
@media (prefers-reduced-motion: reduce) {
  .start-btn { transition: background 0.18s; }
  .start-btn:hover { transform: none; }
  .scroll-cue svg, .pano img { animation: none; }
  .entry:hover .entry-img img { transform: none; }
  .hero-bg img, .hero-body, .entry-img { transform: none; transition: none; }
}
</style>

<style>
/* 自訂游標：深色圓點＋白邊（亮暗背景都看得清楚）；可點的元素換成暖灰圓；拖曳區在 CompareSlider 內用 --cur-drag。
   觸控裝置沒有游標，不受影響；圖檔載入失敗會退回系統游標。 */
.home {
  --cur-default: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20width='36'%20height='36'%20viewBox='0%200%2036%2036'%3E%3Ccircle%20cx='18'%20cy='18'%20r='12'%20fill='none'%20stroke='%23141210'%20stroke-opacity='.18'%20stroke-width='3'/%3E%3Ccircle%20cx='18'%20cy='18'%20r='9'%20fill='%23fff'%20stroke='%23141210'%20stroke-opacity='.5'%20stroke-width='1.2'/%3E%3C/svg%3E") 18 18, auto;
  --cur-pointer: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20width='48'%20height='48'%20viewBox='0%200%2048%2048'%3E%3Ccircle%20cx='24'%20cy='24'%20r='19'%20fill='none'%20stroke='%23141210'%20stroke-opacity='.18'%20stroke-width='3'/%3E%3Ccircle%20cx='24'%20cy='24'%20r='16'%20fill='%23fff'%20fill-opacity='.35'%20stroke='%23fff'%20stroke-width='2.2'/%3E%3Ccircle%20cx='24'%20cy='24'%20r='16.9'%20fill='none'%20stroke='%23141210'%20stroke-opacity='.45'%20stroke-width='.9'/%3E%3C/svg%3E") 24 24, pointer;
  --cur-drag: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20width='64'%20height='44'%20viewBox='0%200%2064%2044'%3E%3Ccircle%20cx='32'%20cy='22'%20r='20'%20fill='none'%20stroke='%23141210'%20stroke-opacity='.18'%20stroke-width='3'/%3E%3Ccircle%20cx='32'%20cy='22'%20r='17'%20fill='%23fff'%20stroke='%23141210'%20stroke-opacity='.5'%20stroke-width='1.2'/%3E%3Cpath%20d='M25%2015l-7%207%207%207M39%2015l7%207-7%207'%20fill='none'%20stroke='%23141210'%20stroke-width='2.2'%20stroke-linecap='round'%20stroke-linejoin='round'/%3E%3C/svg%3E") 32 22, ew-resize;
  cursor: var(--cur-default);
}
.home :is(a, button, [role='button'], summary) { cursor: var(--cur-pointer) !important; }
.home :is(button:disabled) { cursor: not-allowed !important; }
</style>
