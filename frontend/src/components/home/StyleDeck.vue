<script setup>
/**
 * 風格牌卡示範（純展示，使用者不能輸入，也不連風格資料庫，內建範例循環播放）：
 * 1. 資料庫有 3,000+ 張：一排排小卡片像河流一樣流過，前面扇形展開 8 種風格各一張；展示完流動的卡片淡出（只播一次，之後背景保持乾淨）。
 * 2. 輸入條自己打一句口語需求 → 抓出 6 張最相近的風格參考圖，散開成扇形。
 * 3. 白色圓圈游標點其中一張 → 這張的標籤飛向「你的設計圖」，原圖被掃描線改成該風格 → 換下一句，循環。
 *
 * 每個情境的 6 張卡，風格名稱與標籤取自平台語意搜尋（智慧風格推薦）的真實結果：
 * 大多是 1 到 2 種相近風格，每張有各自的標籤。卡片圖是自己生成的範例圖（scripts/gen_home_cards*.py），
 * 設計圖是同一張原圖經平台的 FAL + ControlNet 流程改成各風格（scripts/gen_home_demo.py）。
 */
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { prefersReducedMotion } from '@/composables/useScrollProgress'
import original from '@/assets/home/demo-original.jpg'
import dModern from '@/assets/home/demo-modern.jpg'
import dIndustrial from '@/assets/home/demo-industrial.jpg'
import dLuxury from '@/assets/home/demo-luxury.jpg'
import dJapanese from '@/assets/home/demo-japanese.jpg'
import dCountry from '@/assets/home/demo-country.jpg'
import dNordic from '@/assets/home/demo-nordic.jpg'
import dAmerican from '@/assets/home/demo-american.jpg'
import dClassic from '@/assets/home/demo-classic.jpg'

const CARD = import.meta.glob('/src/assets/home/card-*.jpg', { eager: true, import: 'default' })
const ci = (n) => CARD[`/src/assets/home/card-${n}.jpg`]
const RENDER = { modern: dModern, industrial: dIndustrial, luxury: dLuxury, japanese: dJapanese, country: dCountry, nordic: dNordic, american: dAmerican, classic: dClassic }
const STEPS = ['說出想法', '找到相近的風格', '一鍵套用到設計圖']

// 風格名稱與系統介面一致（/api/style-search 回傳的 style_name）
const NAMES = { modern: '現代簡約', country: '奶油溫馨', classic: '無印生活', nordic: '北歐自然', industrial: '現代工業', japanese: '日式禪意', american: '美式暖居', luxury: '現代輕奢' }
const TAGS = {
  modern: ['簡潔線條', '黑白灰', '玻璃與鉻金屬'], country: ['奶油色', '溫馨', '碎花布'], classic: ['原木', '留白', '收納'],
  nordic: ['白樺木', '白牆', '自然採光'], industrial: ['裸露水泥', '紅磚', '黑色鋼構'], japanese: ['淺橡木', '榻榻米', '柔和光線'],
  american: ['暖木色', '格紋亞麻', '舒適沙發'], luxury: ['大理石', '金銅點綴', '水晶吊燈'],
}
const FEATURED = Object.keys(NAMES).map((id) => ({ id: 'f-' + id, styleId: id, name: NAMES[id], img: ci(id), tags: TAGS[id] }))

// 真實搜尋結果（依相似度排序；s=風格，t=該張的標籤，img=範例圖；pick=游標點的那張）
const SCENES = [
  { q: '家裡有小孩和老人，想要可愛溫暖的感覺', pick: 0, cards: [
    { s: 'american', t: ['童趣', '溫馨', '簡約'], img: 'american' },
    { s: 'country', t: ['溫馨', '舒適', '居家'], img: 'country' },
    { s: 'american', t: ['童趣', '溫馨', '淺色系'], img: 'american-2' },
    { s: 'country', t: ['溫馨', '木質', '復古'], img: 'country-2' },
    { s: 'industrial', t: ['復古', '溫馨', '木質'], img: 'industrial' },
    { s: 'american', t: ['溫馨', '舒適', '沉穩'], img: 'american-3' },
  ] },
  { q: '小坪數，想看起來寬敞明亮一點', pick: 0, cards: [
    { s: 'modern', t: ['極簡', '機能性', '淺木色'], img: 'modern' },
    { s: 'modern', t: ['簡約', '明亮', '實用'], img: 'modern-2' },
    { s: 'modern', t: ['簡約', '機能性', '淺色系'], img: 'modern-3' },
    { s: 'modern', t: ['簡約', '開放式', '明亮'], img: 'modern-4' },
    { s: 'modern', t: ['簡潔', '自然光', '開放式'], img: 'modern-5' },
    { s: 'modern', t: ['簡約', '開放式', '機能性'], img: 'modern-6' },
  ] },
  { q: '喜歡咖啡廳的悠閒氛圍', pick: 1, cards: [
    { s: 'country', t: ['簡約', '綠色系', '溫馨'], img: 'country' },
    { s: 'industrial', t: ['粗獷', '金屬', '木質'], img: 'industrial' },
    { s: 'classic', t: ['優雅', '深色調', '復古'], img: 'classic' },
    { s: 'industrial', t: ['粗獷', '簡約', '復古'], img: 'industrial-2' },
    { s: 'industrial', t: ['裸露管線', '金屬', '木質'], img: 'industrial-3' },
    { s: 'industrial', t: ['粗獷', '金屬', '水泥'], img: 'industrial-4' },
  ] },
  { q: '想要像飯店一樣有質感、放鬆', pick: 1, cards: [
    { s: 'classic', t: ['現代簡約', '大地色系', '低調奢華'], img: 'classic' },
    { s: 'luxury', t: ['現代奢華', '優雅', '明亮'], img: 'luxury' },
    { s: 'luxury', t: ['現代', '大理石', '木質'], img: 'luxury-2' },
    { s: 'luxury', t: ['低調奢華', '東方元素', '精緻'], img: 'luxury-3' },
    { s: 'american', t: ['優雅', '古典', '柔和色調'], img: 'american-3' },
    { s: 'modern', t: ['沉穩', '精緻', '簡約'], img: 'modern' },
  ] },
].map((sc, si) => ({
  ...sc,
  cards: sc.cards.map((c, i) => ({ id: `s${si}-${i}`, styleId: c.s, name: NAMES[c.s], img: ci(c.img), tags: c.t })),
}))

// 開場的流動卡片：3 排範例圖，方向與速度各異，只在第 1 幕出現
const POOL = Object.values(CARD)
const FLOW = [0, 1, 2].map((r) => Array.from({ length: 12 }, (_, i) => ({ k: `${r}-${i}`, img: POOL[(i * 5 + r * 7) % POOL.length], rot: ((i * 37 + r * 11) % 7) - 3 })))

const reduced = prefersReducedMotion()
const backs = (n) => Array.from({ length: n }, (_, i) => ({ id: 'ph' + i, loading: true, tags: [] }))

const cards = ref(backs(8))
const phase = ref('stack')       // stack：一疊；fan：扇形
const flowOn = ref(false)        // 第 1 幕：流動的卡片
const barOn = ref(true)          // 第 1 幕開場先不出現輸入條
const typed = ref('')
const step = ref(0)
const pickId = ref(null)
const appliedName = ref('')
const baseImg = ref(original)
const nextImg = ref(null)
const wipe = ref(0)
const scanning = ref(false)
const cursorShow = ref(false)
const clicking = ref(false)
const flyShow = ref(false)
const flyTags = ref([])
const playing = ref(!reduced)
const hovering = ref(false)
const visible = ref(false)

const root = ref(null)
const wrap = ref(null)
const stage = ref(null)
const bar = ref(null)
const design = ref(null)
const cursorEl = ref(null)
const tagEls = ref([])
const stageW = ref(640)
const cardW = ref(150)

let libraryDone = false
let runId = 0
let io
let ro
const timers = new Set()

/* ── 先把圖載入，播放時才不會跳出來 ── */
function warm() {
  for (const u of [original, ...Object.values(RENDER), ...POOL]) { const im = new Image(); im.src = u }
}

/* ── 牌的位置 ── */
function measure() {
  if (!stage.value) return
  stageW.value = stage.value.clientWidth
  cardW.value = parseFloat(getComputedStyle(stage.value).getPropertyValue('--cw')) || 150
}
const pos = computed(() => {
  const n = cards.value.length
  const c = (n - 1) / 2
  const span = Math.min(stageW.value - cardW.value * 2, (n - 1) * cardW.value * 0.7)
  const step = n > 1 ? span / (n - 1) : 0
  const rot = n > 6 ? 4.2 : 5.5
  return cards.value.map((_, i) => {
    if (phase.value === 'stack') return { x: 0, y: (i % 3) * 2, r: ((i * 37) % 11 - 5) * 0.5, z: i }
    const d = i - c
    return { x: d * step, y: Math.pow(Math.abs(d), 1.7) * 11, r: d * rot, z: 100 - Math.round(Math.abs(d) * 10) }
  })
})
const slotStyle = (i) => {
  const p = pos.value[i]
  return {
    '--x': p.x + 'px', '--y': p.y + 'px', '--r': p.r + 'deg', zIndex: p.z,
    transitionDelay: reduced ? '0s' : (phase.value === 'fan' ? i * 55 : (cards.value.length - i) * 30) + 'ms',
  }
}

/* ── 播放控制 ── */
const paused = () => !playing.value || hovering.value || !visible.value || document.hidden
const alive = (id) => id === runId && playing.value
function pace(ms) {          // 暫停（滑入、離開畫面、分頁隱藏、按暫停）時時間不前進
  return new Promise((resolve) => {
    let t = 0
    let h
    const tick = () => {
      timers.delete(h)
      if (!paused()) t += 50
      if (t >= ms) resolve()
      else { h = setTimeout(tick, 50); timers.add(h) }
    }
    h = setTimeout(tick, 50)
    timers.add(h)
  })
}
const center = (el, wr, fx = 0.5, fy = 0.5) => {
  const r = el.getBoundingClientRect()
  return { x: r.left - wr.left + r.width * fx, y: r.top - wr.top + r.height * fy, r }
}
function animateWipe(ms) {
  return new Promise((res) => {
    if (reduced) { wipe.value = 100; res(); return }
    const t0 = performance.now()
    const stepf = (now) => {
      const k = Math.min(1, (now - t0) / ms)
      wipe.value = 100 * (1 - Math.pow(1 - k, 2))
      if (k < 1) requestAnimationFrame(stepf); else res()
    }
    requestAnimationFrame(stepf)
  })
}
async function swapDesign(to, ms) {
  nextImg.value = to
  wipe.value = 0
  scanning.value = true
  await animateWipe(ms)
  baseImg.value = to
  nextImg.value = null
  wipe.value = 0
  scanning.value = false
}

/* 第 1 幕：資料庫有 3,000+ 張，前面展開 8 種風格各一張 */
async function runLibrary(id) {
  step.value = 0; pickId.value = null; appliedName.value = ''; typed.value = ''
  flowOn.value = true; barOn.value = false     // 開場只有流動的圖
  phase.value = 'stack'
  cards.value = []
  await pace(3800)
  if (!alive(id)) return
  barOn.value = true                           // 輸入條出現，8 張風格卡從流動的圖裡拉出來；兩者不同時存在
  flowOn.value = false
  cards.value = FEATURED.map((c) => ({ ...c }))
  await nextTick()
  await pace(500)
  phase.value = 'fan'
  await pace(3600)
  if (!alive(id)) return
  phase.value = 'stack'
  await pace(900)
  libraryDone = true
}

async function runScene(si, id) {
  const sc = SCENES[si]
  if (!libraryDone && !reduced) { await runLibrary(id); if (!alive(id)) return }
  barOn.value = true
  // 重置
  step.value = 0; pickId.value = null; appliedName.value = ''; typed.value = ''
  flyShow.value = false; flyTags.value = []; cursorShow.value = false
  if (baseImg.value !== original) await swapDesign(original, 500)
  phase.value = 'stack'
  cards.value = []
  flowOn.value = !reduced        // 打字時背景是流動的圖，快打完才從裡面抓出結果
  if (!alive(id)) return
  const chosen = sc.cards[sc.pick]
  await pace(500)
  // 1 說出想法
  step.value = 1
  const chars = [...sc.q]
  for (const [k, ch] of chars.entries()) {
    if (!alive(id)) return
    typed.value += ch
    if (k === chars.length - 3) cards.value = sc.cards.map((c) => ({ ...c }))   // 快打完：卡片先疊在原處
    await pace(75)
  }
  if (!alive(id)) return
  // 2 從流動的圖裡抓出相近的 6 張
  step.value = 2
  flowOn.value = false
  await nextTick()
  phase.value = 'fan'
  await pace(1500)
  if (!alive(id)) return
  // 3 游標點牌
  step.value = 3
  const wr = wrap.value.getBoundingClientRect()
  const slot = stage.value.querySelector(`[data-id="${chosen.id}"]`)
  const br = center(bar.value, wr, 0.92, 0.5)
  const target = center(slot, wr, 0.5, 0.42)
  cursorShow.value = true
  await nextTick()
  const cur = cursorEl.value
  if (reduced) cur.style.transform = `translate(${target.x}px, ${target.y}px)`
  else {
    cur.style.transform = `translate(${br.x}px, ${br.y}px)`
    await cur.animate([{ transform: `translate(${br.x}px, ${br.y}px)` }, { transform: `translate(${target.x}px, ${target.y}px)` }],
      { duration: 1000, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' }).finished
  }
  if (!alive(id)) return
  clicking.value = true
  await pace(280)
  clicking.value = false
  pickId.value = chosen.id
  await pace(650)
  if (!alive(id)) return
  // 4 把這張的風格套用到設計圖：標籤飛向設計圖，原圖被掃描線改成該風格
  const wr2 = wrap.value.getBoundingClientRect()
  const dr = center(design.value, wr2)
  const from = center(slot.querySelector('.card') || slot, wr2)
  flyTags.value = chosen.tags.slice(0, 3)
  flyShow.value = true
  await nextTick()
  const dx = dr.x - from.x
  const dy = dr.y - from.y
  const jobs = []
  tagEls.value.filter(Boolean).forEach((el) => el.getAnimations().forEach((a) => a.cancel()))
  if (!reduced) {
    tagEls.value.filter(Boolean).forEach((el, i) => {
      Object.assign(el.style, { left: from.x + 'px', top: from.y + 'px' })
      const off = [[-110, -50], [0, 10], [110, 60]][i] || [0, 0]
      jobs.push(el.animate([
        { transform: 'translate(-50%,-50%) scale(0.6)', opacity: 0 },
        { transform: 'translate(-50%,-50%) scale(1)', opacity: 1, offset: 0.2 },
        { transform: `translate(calc(-50% + ${dx + off[0]}px), calc(-50% + ${dy + off[1]}px)) scale(1)`, opacity: 1, offset: 0.8 },
        { transform: `translate(calc(-50% + ${dx + off[0]}px), calc(-50% + ${dy + off[1]}px)) scale(0.8)`, opacity: 0 },
      ], { duration: 1100, delay: i * 120, easing: 'ease-in-out', fill: 'forwards' }).finished)
    })
    await pace(750)
  }
  if (!alive(id)) return
  const sweep = swapDesign(RENDER[chosen.styleId], 1200)
  await Promise.all([sweep, ...jobs.map((j) => j.catch(() => {}))])
  flyShow.value = false
  cursorShow.value = false
  appliedName.value = chosen.name
  await pace(2600)
}
async function loop() {
  const id = ++runId
  while (alive(id)) {
    for (let i = 0; i < SCENES.length && alive(id); i++) {
      while (alive(id) && paused()) await new Promise((r) => setTimeout(r, 250))
      if (!alive(id)) return
      await runScene(i, id)
    }
  }
}
function showFinal() {   // 減少動態：不播放，直接顯示第一個情境的最後畫面
  const sc = SCENES[0]
  const chosen = sc.cards[sc.pick]
  cards.value = sc.cards
  phase.value = 'fan'
  typed.value = sc.q
  step.value = 3
  pickId.value = chosen.id
  baseImg.value = RENDER[chosen.styleId]
  appliedName.value = chosen.name
}

onMounted(() => {
  measure()
  ro = new ResizeObserver(measure)
  ro.observe(stage.value)
  io = new IntersectionObserver(([e]) => { visible.value = e.isIntersecting }, { threshold: 0.3 })
  io.observe(root.value)
  warm()
  if (reduced) showFinal(); else loop()
  startCount()
})
onBeforeUnmount(() => { runId++; playing.value = false; timers.forEach(clearTimeout); io?.disconnect(); ro?.disconnect(); cio?.disconnect(); cancelAnimationFrame(raf) })

/* ── 標題的數字滾動 ── */
const TARGET = 3000
const shown = ref(reduced ? '3,000' : '0')
let raf = 0
let cio
const head = ref(null)
function startCount() {
  if (reduced) return
  cio = new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) return
    cio.disconnect()
    const t0 = performance.now()
    const stepf = (now) => {
      const k = Math.min(1, (now - t0) / 1600)
      shown.value = Math.round(TARGET * (1 - Math.pow(1 - k, 3))).toLocaleString('en-US')
      if (k < 1) raf = requestAnimationFrame(stepf)
    }
    raf = requestAnimationFrame(stepf)
  }, { threshold: 0.5 })
  cio.observe(head.value)
}
</script>

<template>
  <section ref="root" class="deck" aria-labelledby="deck-h">
    <div ref="head" class="head">
      <p class="eyebrow">8 大風格・每一張都有專屬標籤</p>
      <h2 id="deck-h">
        <span class="sr-only">3,000+</span><span class="num" aria-hidden="true">{{ shown }}+</span>
        張台灣居家風格參考，<br />挑一張，直接套用到你的設計圖
      </h2>
      <p class="lead">每一張參考圖都歸在 8 大風格之一，又各自帶著材質與色彩標籤，所以同一種風格，也能找到不同的味道。</p>
      <ol class="steps" aria-hidden="true">
        <li v-for="(s, i) in STEPS" :key="s" :class="{ on: step === i + 1, done: step > i + 1 }"><b>{{ i + 1 }}</b>{{ s }}</li>
      </ol>
    </div>

    <p class="sr-only">示範動畫：資料庫裡有三千多張風格參考圖；輸入一句口語需求後，系統找出相近的風格，挑一張，把這個風格套用到同一張房間照片上。</p>

    <div ref="wrap" class="wrap" aria-hidden="true" @mouseenter="hovering = true" @mouseleave="hovering = false">
      <div class="left">
        <div class="flow" :class="{ on: flowOn, still: hovering || !visible }">
          <div v-for="(row, r) in FLOW" :key="r" class="row" :class="{ rev: r % 2 }" :style="{ '--dur': 26 + r * 7 + 's' }">
            <div class="track">
              <i v-for="t in [...row, ...row]" :key="t.k + (t === row[0] ? '' : '')" :style="{ backgroundImage: `url(${t.img})`, transform: `rotate(${t.rot}deg)` }"></i>
            </div>
          </div>
        </div>
        <div ref="bar" class="bar" :class="{ off: !barOn }">
          <span class="label">描述你的需求…</span>
          <span class="typed">{{ typed }}<i class="caret"></i></span>
        </div>
        <ul ref="stage" class="stage">
          <li v-for="(c, i) in cards" :key="c.id" class="slot" :data-id="c.id" :class="{ dim: pickId && pickId !== c.id, pick: pickId === c.id }" :style="slotStyle(i)">
            <div class="card">
              <span v-if="c.loading" class="back"><i></i></span>
              <template v-else>
                <span class="pic">
                  <img v-if="c.img" :src="c.img" alt="" loading="lazy" draggable="false" />
                  <span v-else class="ph">{{ c.name }}</span>
                </span>
                <span class="info">
                  <b class="name">{{ c.name }}</b>
                  <span class="tags"><i v-for="t in c.tags" :key="t">{{ t }}</i></span>
                </span>
              </template>
            </div>
          </li>
        </ul>
      </div>

      <div ref="design" class="design">
        <img class="d-base" :class="{ orig: baseImg === original }" :src="baseImg" alt="" draggable="false" />
        <img v-if="nextImg" class="d-next" :src="nextImg" alt="" draggable="false" :style="{ clipPath: `inset(0 ${100 - wipe}% 0 0)` }" />
        <i class="scan" :style="{ left: wipe + '%', opacity: scanning ? 1 : 0 }"></i>
        <span class="chip tl">{{ baseImg === original ? '你的設計圖・原圖' : '你的設計圖' }}</span>
        <span v-if="appliedName" class="chip br">已套用：{{ appliedName }}</span>
      </div>

      <div v-show="flyShow" class="overlay">
        <span v-for="(t, i) in flyTags" :key="t" :ref="(el) => (tagEls[i] = el)" class="flytag">{{ t }}</span>
      </div>

      <svg v-show="cursorShow" ref="cursorEl" class="vcursor" :class="{ click: clicking }" viewBox="0 0 36 36" focusable="false">
        <circle class="ring" cx="18" cy="18" r="12" />
        <circle class="dot" cx="18" cy="18" r="9" />
      </svg>
    </div>


  </section>
</template>

<style scoped>
.deck {
  --cw: 150px;
  --ch: 212px;
  width: min(1180px, calc(100vw - 3rem));
  margin: 0 auto;
  padding: clamp(2rem, 5vw, 4rem) 0 clamp(3.5rem, 8vw, 6rem);
  overflow-x: clip;
}
.eyebrow { margin: 0 0 0.6rem; font-size: 0.82rem; letter-spacing: 0.14em; color: var(--db-accent-ink); }
h2 {
  margin: 0 0 0.9rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.7rem, 3.2vw, 2.5rem);
  line-height: 1.35;
  text-wrap: balance;
  color: var(--db-text);
}
.num { display: inline-block; min-width: 3.9ch; font-family: var(--db-font-num); font-style: normal; font-weight: 500; font-size: 1.3em; line-height: 1; font-variant-numeric: tabular-nums; color: var(--db-accent-ink); margin-right: 0.2em; }
.lead { max-width: 36rem; margin: 0 0 1.25rem; line-height: 1.85; color: var(--db-text-soft); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.steps { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0 0 1.5rem; padding: 0; list-style: none; }
.steps li { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0.9rem 0.3rem 0.4rem; border: 1px solid var(--db-accent-soft); border-radius: var(--db-radius-pill); color: var(--db-text-soft); font-size: 0.88rem; transition: background 0.3s, color 0.3s, border-color 0.3s; }
.steps b { display: grid; place-items: center; width: 1.5rem; height: 1.5rem; border-radius: 50%; background: var(--db-accent-soft); color: var(--db-accent-ink); font-family: var(--db-font-num); font-size: 0.8rem; font-weight: 500; }
.steps li.on { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent); }
.steps li.on b { background: #fff; color: var(--db-text); }
.steps li.done { color: var(--db-text); }

.wrap { position: relative; display: grid; grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); gap: clamp(1rem, 3vw, 2.5rem); align-items: center; padding: 1.25rem 0; }
.left, .design { position: relative; z-index: 1; }
.left { min-width: 0; }
.bar, .stage { position: relative; z-index: 1; }
.bar.off { opacity: 0; }

/* ── 開場的流動卡片：一排排小卡片像河流一樣流過，只在第 1 幕出現 ── */
.flow { position: absolute; left: -1.25rem; right: -1.25rem; top: 3.4rem; height: 17rem; z-index: 0; display: grid; align-content: space-between; opacity: 0; transition: opacity 0.5s ease; pointer-events: none; -webkit-mask-image: linear-gradient(90deg, transparent, #000 14%, #000 86%, transparent); mask-image: linear-gradient(90deg, transparent, #000 14%, #000 86%, transparent); }
.flow.on { opacity: 0.85; }
.row { overflow: hidden; }
.track { display: flex; gap: 12px; width: max-content; animation: slide var(--dur, 30s) linear infinite; }
.row.rev .track { animation-direction: reverse; }
.flow.still .track { animation-play-state: paused; }
.track i { flex: none; width: 74px; height: 98px; border: 3px solid #fff; border-radius: 9px; background-size: cover; background-position: center; box-shadow: 0 4px 12px rgba(28, 24, 18, 0.2); }
@keyframes slide { to { transform: translateX(-50%); } }

.bar { transition: opacity 0.6s ease; max-width: 32rem; padding: 0.7rem 1.1rem; border: 1.5px solid var(--db-accent); border-radius: var(--db-radius-chip); background: #fff; }
.label { display: block; font-size: 0.74rem; letter-spacing: 0.12em; color: var(--db-accent-ink); }
.typed { display: block; min-height: 1.7em; margin-top: 0.1rem; font-size: 1.05rem; color: var(--db-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.typed em { font-style: normal; color: var(--db-text-soft); }
.caret { display: inline-block; width: 2px; height: 1.1em; margin-left: 2px; background: var(--db-text); vertical-align: -0.15em; animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }

/* ── 牌桌 ── */
.stage { position: relative; list-style: none; margin: 1rem 0 0; padding: 0; height: calc(var(--ch) + 110px); }
.slot {
  position: absolute;
  left: 50%;
  top: 24px;
  width: var(--cw);
  height: var(--ch);
  margin-left: calc(var(--cw) / -2);
  transform: translate(var(--x, 0), var(--y, 0)) rotate(var(--r, 0deg));
  transform-origin: 50% 120%;
  transition: transform 0.85s cubic-bezier(0.2, 0.9, 0.25, 1), opacity 0.4s, filter 0.4s;
}
.slot.dim { opacity: 0.42; filter: saturate(0.6); }
.slot.pick { z-index: 300 !important; }
.slot.pick .card { transform: translateY(-26px) scale(1.1); box-shadow: 0 24px 44px rgba(28, 24, 18, 0.34); outline: 3px solid var(--db-text); outline-offset: 2px; }
.card {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  border: 6px solid #fff;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 10px 26px rgba(28, 24, 18, 0.22);
  overflow: hidden;
  transition: transform 0.4s cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 0.4s;
}
.back { flex: 1; display: grid; place-items: center; background: repeating-linear-gradient(45deg, var(--db-accent-soft) 0 8px, #fff 8px 16px); }
.back i { width: 38%; aspect-ratio: 1; border-radius: 50%; border: 3px solid var(--db-accent-ink); opacity: 0.55; }
.pic { position: relative; flex: 1; min-height: 0; background: var(--db-accent-soft); }
.pic img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.ph { position: absolute; inset: 0; display: grid; place-items: center; font-family: var(--db-font-display); font-style: italic; font-size: 1.2rem; color: var(--db-accent-ink); }
.info { display: grid; gap: 0.3rem; padding: 0.5rem 0.6rem 0.6rem; background: #fff; }
.name { font-family: var(--db-font-display); font-weight: 500; font-size: 0.98rem; color: var(--db-text); }
.tags { display: flex; flex-wrap: wrap; gap: 0.22rem; }
.tags i { font-style: normal; padding: 0.08rem 0.45rem; border-radius: var(--db-radius-pill); background: var(--db-accent-soft); color: var(--db-accent-ink); font-size: 0.68rem; }

/* ── 設計圖：原圖拉伸成 16:9（與生成流程輸出的比例一致，前後對得上）── */
.design { aspect-ratio: 16 / 9; border-radius: var(--db-radius-card); overflow: hidden; background: var(--db-accent-soft); box-shadow: var(--db-shadow-card); }
.design img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.design img.orig { object-fit: fill; }
.scan { position: absolute; top: 0; bottom: 0; width: 3px; margin-left: -1px; background: #fff; box-shadow: 0 0 14px 3px rgba(255, 255, 255, 0.85); transition: opacity 0.2s; }
.chip { position: absolute; padding: 0.3rem 0.85rem; border-radius: var(--db-radius-pill); background: rgba(20, 18, 14, 0.62); color: #fff; font-family: var(--db-font-display); font-size: 0.92rem; backdrop-filter: blur(6px); }
.chip.tl { left: 0.9rem; top: 0.9rem; }
.chip.br { right: 0.9rem; bottom: 0.9rem; }

/* ── 飛行的標籤、游標 ── */
.overlay { position: absolute; inset: 0; pointer-events: none; z-index: 500; }
.flytag { position: absolute; padding: 0.25rem 0.8rem; border-radius: var(--db-radius-pill); background: #fff; color: var(--db-text); font-size: 0.82rem; box-shadow: var(--db-shadow-soft); white-space: nowrap; opacity: 0; }
.vcursor { position: absolute; left: -18px; top: -18px; width: 36px; height: 36px; z-index: 600; pointer-events: none; overflow: visible; filter: drop-shadow(0 2px 4px rgba(20, 18, 14, 0.35)); }
.vcursor .ring { fill: none; stroke: #141210; stroke-opacity: 0.18; stroke-width: 3; }
.vcursor .dot { fill: #fff; stroke: #141210; stroke-opacity: 0.5; stroke-width: 1.2; transform-origin: 18px 18px; }
.vcursor.click .dot { animation: press 0.28s ease; }
.vcursor.click .ring { animation: ripple 0.5s ease-out; }
@keyframes press { 50% { transform: scale(0.72); } }
@keyframes ripple { from { r: 12; stroke-opacity: 0.5; } to { r: 22; stroke-opacity: 0; } }

.foot { display: flex; align-items: center; flex-wrap: wrap; gap: 0.75rem 1.25rem; margin-top: 1.25rem; }
.note { margin: 0; font-size: 0.82rem; color: var(--db-text-soft); }

@media (max-width: 860px) {
  .deck { --cw: 128px; --ch: 182px; }
  .wrap { grid-template-columns: 1fr; }
  .stage { height: calc(var(--ch) + 100px); }
  .name { font-size: 0.88rem; }
}
@media (prefers-reduced-motion: reduce) {
  .slot, .card, .steps li { transition: none; }
  .flow { display: none; }
  .caret { animation: none; }
}
</style>
