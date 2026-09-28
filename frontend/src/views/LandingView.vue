<script setup>
// ponytail: 已無路由指向這個檔案（router/index.js 的 /landing 已移除）。
// 沒有入口連過去的深色行銷展示頁，確認不再需要之後可以整份刪除。
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

/* ───────────────────────── environment flags ───────────────────────── */
const finePointer = window.matchMedia('(pointer: fine)').matches
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const liteMode =
  reducedMotion ||
  !finePointer ||
  window.matchMedia('(max-width: 768px)').matches

/* ───────────────────────── loader ───────────────────────── */
const loaderLeaving = ref(false)
const loaderGone = ref(false)
const heroIn = ref(false)

/* ───────────────────────── hero copy ───────────────────────── */
const heroChars = '重新定義你與空間的對話'.split('')
const goldChars = new Set([6, 7]) // 空間

/* ───────────────────────── scroll reveals ───────────────────────── */
const revealed = reactive(new Set())

/* ───────────────────────── section 2 · before / after ───────────────────────── */
const rooms = [
  { id: 'living', name: '客廳', desc: '從毛胚到溫潤木質調，一句話完成。' },
  { id: 'bedroom', name: '臥室', desc: '光線、織品與留白的平衡。' },
  { id: 'study', name: '書房', desc: '為專注而生的安靜角落。' },
]
const baPos = reactive({ living: 50, bedroom: 50, study: 50 })
let baDrag = null // { id, rect }

function baDown(e, id) {
  const rect = e.currentTarget.getBoundingClientRect()
  baDrag = { id, rect }
  baMoveTo(e.clientX)
  e.preventDefault()
}
function baMoveTo(clientX) {
  if (!baDrag) return
  const { id, rect } = baDrag
  const pct = ((clientX - rect.left) / rect.width) * 100
  baPos[id] = Math.min(94, Math.max(6, pct))
}
function onWinPointerMove(e) { if (baDrag) baMoveTo(e.clientX) }
function onWinPointerUp() { baDrag = null }

function tilt(e) {
  if (liteMode) return
  const el = e.currentTarget
  const r = el.getBoundingClientRect()
  const px = (e.clientX - r.left) / r.width - 0.5
  const py = (e.clientY - r.top) / r.height - 0.5
  el.style.setProperty('--rx', `${(-py * 4).toFixed(2)}deg`)
  el.style.setProperty('--ry', `${(px * 5).toFixed(2)}deg`)
}
function untilt(e) {
  e.currentTarget.style.setProperty('--rx', '0deg')
  e.currentTarget.style.setProperty('--ry', '0deg')
}

/* ───────────────────────── section 3 · pipeline ───────────────────────── */
const agents = [
  { name: '需求解析', x: 130, y: 150, desc: '把你的一句話拆解成空間需求、機能與生活偏好，建立設計任務的藍圖。' },
  { name: '空間分析', x: 390, y: 90, desc: '辨識格局、採光方向與既有家具配置，理解這個空間真正的條件。' },
  { name: '風格檢索', x: 650, y: 170, desc: '從風格知識庫比對最契合的設計語彙，找出屬於你的視覺基因。' },
  { name: '佈局規劃', x: 910, y: 90, desc: '規劃動線與家具配置，在美感與機能之間找到最好的平衡。' },
  { name: '渲染生成', x: 1170, y: 170, desc: '以擴散模型生成擬真效果圖，讓想像在幾秒內變成可見的畫面。' },
  { name: '品質審查', x: 1430, y: 110, desc: '檢核成果與需求的一致性，確保每張圖都經得起專業的眼光。' },
]
const pipeD = agents
  .map((a, i) => {
    if (i === 0) return `M${a.x} ${a.y}`
    const p = agents[i - 1]
    return `C ${p.x + 120} ${p.y}, ${a.x - 120} ${a.y}, ${a.x} ${a.y}`
  })
  .join(' ')
const openNode = ref(-1)
const pipeWords = ['從一句話', '到完整設計圖，', '六位 AI 專家', '在幕後接力 —', '理解', '、分析', '、檢索', '、規劃', '、生成', '、審查，', '每一步', '都有專人把關。']
const pipeHeadChars = '六個專家，一次協作'.split('')

let pipeDragState = null
function pipeDragStart(e) {
  const el = pipeScrollEl.value
  pipeDragState = { x: e.clientX, sl: el.scrollLeft, moved: false }
}
function pipeDragMove(e) {
  if (!pipeDragState) return
  const dx = e.clientX - pipeDragState.x
  if (Math.abs(dx) > 4) pipeDragState.moved = true
  pipeScrollEl.value.scrollLeft = pipeDragState.sl - dx
}
function pipeDragEnd() { pipeDragState = null }

/* ───────────────────────── section 4 · style selector ───────────────────────── */
const styles = [
  {
    id: 'modern', label: '現代風',
    filter: 'contrast(1.08) saturate(.85) brightness(1.04)',
    overlay: 'linear-gradient(155deg, rgba(74,111,165,.20), rgba(13,13,13,.06) 65%)',
    chips: ['俐落線條', '中性色調', '開放格局', '金屬細節'],
  },
  {
    id: 'nordic', label: '北歐風',
    filter: 'brightness(1.18) saturate(.72) contrast(.96)',
    overlay: 'linear-gradient(165deg, rgba(240,237,230,.12), rgba(143,163,189,.10) 70%)',
    chips: ['原木質感', '自然採光', '簡約留白', '溫潤織品'],
  },
  {
    id: 'industrial', label: '工業風',
    filter: 'grayscale(.45) contrast(1.22) brightness(.82)',
    overlay: 'linear-gradient(170deg, rgba(30,32,36,.35), rgba(74,111,165,.10) 75%)',
    chips: ['裸露結構', '金屬骨架', '灰階層次', '復古燈具'],
  },
  {
    id: 'wabi', label: '日式侘寂',
    filter: 'sepia(.32) saturate(.62) brightness(.97)',
    overlay: 'linear-gradient(160deg, rgba(201,169,110,.14), rgba(58,51,42,.18) 70%)',
    chips: ['侘寂質地', '低彩度', '手作陶器', '靜謐氛圍'],
  },
  {
    id: 'classical', label: '古典風',
    filter: 'sepia(.45) saturate(1.28) contrast(1.06)',
    overlay: 'linear-gradient(150deg, rgba(201,169,110,.22), rgba(38,28,16,.20) 75%)',
    chips: ['古典線板', '對稱布局', '深色木質', '水晶光暈'],
  },
  {
    id: 'cream', label: '奶油風',
    filter: 'brightness(1.22) saturate(.82) sepia(.16)',
    overlay: 'linear-gradient(160deg, rgba(247,240,232,.16), rgba(216,191,154,.12) 70%)',
    chips: ['奶油色調', '圓潤曲線', '柔霧質感', '布藝包覆'],
  },
]
const activeTagIdx = ref(0)
const displayedIdx = ref(0)
const generating = ref(false)
const displayedStyle = computed(() => styles[displayedIdx.value])
const underlineStyle = ref({ left: '0px', width: '0px' })
const tagEls = []
let genTimer = null

function setTagRef(el, i) { if (el) tagEls[i] = el }
function moveUnderline() {
  const el = tagEls[activeTagIdx.value]
  if (!el) return
  underlineStyle.value = { left: `${el.offsetLeft}px`, width: `${el.offsetWidth}px` }
}
function selectStyle(i) {
  if (i === activeTagIdx.value && i === displayedIdx.value) return
  activeTagIdx.value = i
  nextTick(moveUnderline)
  clearTimeout(genTimer)
  generating.value = true
  genTimer = setTimeout(() => {
    displayedIdx.value = i
    generating.value = false
  }, 600)
}

/* ───────────────────────── section 5 · stats ───────────────────────── */
const stats = [
  { n: 10, suffix: '+', label: '支援風格', frac: 0.78 },
  { n: 500, suffix: '+', label: '訓練樣本', frac: 0.92 },
  { n: 6, suffix: '', label: '專業 Agent', frac: 0.6 },
]
const counts = ref([0, 0, 0])
const statsOn = ref(false)
let statsStarted = false

function startStats() {
  if (statsStarted) return
  statsStarted = true
  statsOn.value = true
  if (reducedMotion) {
    counts.value = stats.map((s) => s.n)
    return
  }
  const t0 = performance.now()
  const dur = 1800
  const tick = (now) => {
    const t = Math.min(1, (now - t0) / dur)
    const ease = 1 - Math.pow(1 - t, 3)
    counts.value = stats.map((s) => Math.round(s.n * ease))
    if (t < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

/* ───────────────────────── custom cursor ───────────────────────── */
const cursorMode = ref('')
function onHoverCheck(e) {
  const t = e.target
  if (!t || !t.closest) return
  if (t.closest('.ba-handle, a, button, .agent-node')) cursorMode.value = 'hover'
  else if (t.closest('.ba-stage, .demo-stage')) cursorMode.value = 'explore'
  else cursorMode.value = ''
}

/* ───────────────────────── cta ───────────────────────── */
const ctaHover = ref(false)
const CTA_DOT_COUNT = 18
let ctaDots = [] // { el, hx, hy, x, y, ph }
let btnLocal = { x: 0, y: 0 }

function goApp() { router.push('/') }

/* ───────────────────────── element refs ───────────────────────── */
const rootEl = ref(null)
const dotEl = ref(null)
const ringEl = ref(null)
const canvasEl = ref(null)
const heroEl = ref(null)
const pipeScrollEl = ref(null)
const pipePathEl = ref(null)
const packetEl = ref(null)
const ctaEl = ref(null)
const ctaBtnWrap = ref(null)
const ctaBtn = ref(null)
const ctaDotEls = []
function setCtaDotRef(el, i) { if (el) ctaDotEls[i] = el }

/* ───────────────────────── master animation loop ───────────────────────── */
let rafId = 0
let mx = window.innerWidth / 2
let my = window.innerHeight / 2
let ringX = mx
let ringY = my
let heroVisible = true
let pipeVisible = false
let ctaVisible = false
let canvasRect = { left: 0, top: 0 }
let btnWrapRect = null
let pathLen = 0
let ctx = null
let W = 0
let H = 0
const particles = []

function initParticles() {
  const c = canvasEl.value
  if (!c) return
  const dpr = window.devicePixelRatio || 1
  W = c.clientWidth
  H = c.clientHeight
  c.width = W * dpr
  c.height = H * dpr
  ctx = c.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  if (!particles.length) {
    for (let i = 0; i < 120; i++) {
      const r = Math.random
      particles.push({
        x: r() * W, y: r() * H,
        vx: (r() - 0.5) * 0.25, vy: (r() - 0.5) * 0.25,
        ph: r() * Math.PI * 2,
        f1: 0.3 + r() * 0.7, f2: 0.3 + r() * 0.7,
        s: 1 + r() * 1.6,
      })
    }
  }
}

function drawParticles(now) {
  if (!ctx) return
  const t = now * 0.001
  ctx.clearRect(0, 0, W, H)
  const mxc = mx - canvasRect.left
  const myc = my - canvasRect.top

  for (const p of particles) {
    // layered sin/cos drift — organic, Perlin-ish motion
    p.x += p.vx + Math.sin(t * p.f1 + p.ph) * 0.18 + Math.sin(t * 0.31 + p.ph * 2.3) * 0.06
    p.y += p.vy + Math.cos(t * p.f2 + p.ph * 1.7) * 0.18 + Math.cos(t * 0.27 + p.ph * 1.1) * 0.06

    const dx = mxc - p.x
    const dy = myc - p.y
    const d2 = dx * dx + dy * dy
    if (d2 < 40000 && d2 > 1) {
      const d = Math.sqrt(d2)
      const f = (1 - d / 200) * 0.045
      p.vx += (dx / d) * f
      p.vy += (dy / d) * f
    }
    p.vx *= 0.985
    p.vy *= 0.985

    if (p.x < -20) p.x = W + 20
    else if (p.x > W + 20) p.x = -20
    if (p.y < -20) p.y = H + 20
    else if (p.y > H + 20) p.y = -20
  }

  ctx.lineWidth = 1
  for (let i = 0; i < particles.length; i++) {
    const a = particles[i]
    for (let j = i + 1; j < particles.length; j++) {
      const b = particles[j]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const d2 = dx * dx + dy * dy
      if (d2 < 14400) {
        const alpha = (1 - Math.sqrt(d2) / 120) * 0.3
        ctx.strokeStyle = `rgba(201,169,110,${alpha.toFixed(3)})`
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()
      }
    }
  }
  for (const p of particles) {
    ctx.fillStyle = 'rgba(201,169,110,.75)'
    ctx.beginPath()
    ctx.arc(p.x, p.y, p.s, 0, Math.PI * 2)
    ctx.fill()
  }
}

function movePacket(now) {
  const path = pipePathEl.value
  const pk = packetEl.value
  if (!path || !pk) return
  if (!pathLen) pathLen = path.getTotalLength()
  const t = (now % 4200) / 4200
  const pt = path.getPointAtLength(t * pathLen)
  pk.setAttribute('transform', `translate(${pt.x.toFixed(1)} ${pt.y.toFixed(1)})`)
}

function initCtaDots() {
  const sec = ctaEl.value
  const wrap = ctaBtnWrap.value
  if (!sec || !wrap) return
  const sw = sec.offsetWidth
  const sh = sec.offsetHeight
  btnLocal = { x: wrap.offsetLeft + wrap.offsetWidth / 2, y: wrap.offsetTop + wrap.offsetHeight / 2 }
  ctaDots = ctaDotEls.slice(0, CTA_DOT_COUNT).map((el, i) => {
    const hx = sw * (0.08 + Math.random() * 0.84)
    const hy = sh * (0.12 + Math.random() * 0.72)
    el.style.left = `${hx}px`
    el.style.top = `${hy}px`
    return { el, hx, hy, x: 0, y: 0, ph: i * 1.37 }
  })
}

function moveCtaDots(now) {
  for (const d of ctaDots) {
    const driftX = Math.sin(now * 0.0004 + d.ph) * 16
    const driftY = Math.cos(now * 0.0005 + d.ph * 1.3) * 12
    const tx = ctaHover.value ? (btnLocal.x - d.hx) * 0.6 : driftX
    const ty = ctaHover.value ? (btnLocal.y - d.hy) * 0.6 : driftY
    d.x += (tx - d.x) * 0.055
    d.y += (ty - d.y) * 0.055
    d.el.style.transform = `translate3d(${d.x.toFixed(1)}px, ${d.y.toFixed(1)}px, 0)`
  }
}

function loop(now) {
  if (finePointer && dotEl.value) {
    dotEl.value.style.transform = `translate3d(${mx}px, ${my}px, 0) translate(-50%,-50%)`
    ringX += (mx - ringX) * 0.16
    ringY += (my - ringY) * 0.16
    ringEl.value.style.transform = `translate3d(${ringX.toFixed(1)}px, ${ringY.toFixed(1)}px, 0) translate(-50%,-50%)`
  }
  if (heroVisible && !liteMode) drawParticles(now)
  if (pipeVisible && !reducedMotion) movePacket(now)
  if (ctaVisible && !liteMode) moveCtaDots(now)

  // magnetic button
  if (ctaVisible && finePointer && btnWrapRect && ctaBtn.value) {
    const cx = btnWrapRect.left + btnWrapRect.width / 2
    const cy = btnWrapRect.top + btnWrapRect.height / 2
    const dx = mx - cx
    const dy = my - cy
    const d = Math.hypot(dx, dy)
    ctaBtn.value.style.transform = d < 100 ? `translate(${(dx * 0.3).toFixed(1)}px, ${(dy * 0.3).toFixed(1)}px)` : ''
  }
  rafId = requestAnimationFrame(loop)
}

/* ───────────────────────── listeners / observers ───────────────────────── */
let revealIO = null
let visIO = null
let scrollPending = false

function onMouseMove(e) { mx = e.clientX; my = e.clientY }
function refreshRects() {
  if (canvasEl.value) canvasRect = canvasEl.value.getBoundingClientRect()
  if (ctaBtnWrap.value) btnWrapRect = ctaBtnWrap.value.getBoundingClientRect()
}
function onScroll() {
  if (scrollPending) return
  scrollPending = true
  requestAnimationFrame(() => { refreshRects(); scrollPending = false })
}
function onResize() {
  if (scrollPending) return
  scrollPending = true
  requestAnimationFrame(() => {
    if (!liteMode) initParticles()
    refreshRects()
    moveUnderline()
    initCtaDots()
    scrollPending = false
  })
}

onMounted(() => {
  document.documentElement.classList.add('db-landing-active')

  // loading screen → hero entrance
  setTimeout(() => { loaderLeaving.value = true }, reducedMotion ? 100 : 1300)
  setTimeout(() => { loaderGone.value = true; heroIn.value = true }, reducedMotion ? 150 : 2050)

  if (!liteMode) initParticles()
  refreshRects()
  nextTick(() => { moveUnderline(); initCtaDots(); refreshRects() })
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveUnderline)

  // reveal observer
  revealIO = new IntersectionObserver(
    (entries) => {
      for (const en of entries) {
        if (!en.isIntersecting) continue
        const id = en.target.dataset.reveal
        revealed.add(id)
        if (id === 'stats') startStats()
        revealIO.unobserve(en.target)
      }
    },
    { threshold: 0.18 },
  )
  rootEl.value.querySelectorAll('[data-reveal]').forEach((el) => revealIO.observe(el))

  // visibility gating for the animation loop
  visIO = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.target === heroEl.value) heroVisible = en.isIntersecting
      else if (en.target === pipeScrollEl.value) pipeVisible = en.isIntersecting
      else if (en.target === ctaEl.value) ctaVisible = en.isIntersecting
    }
  })
  visIO.observe(heroEl.value)
  visIO.observe(pipeScrollEl.value)
  visIO.observe(ctaEl.value)

  window.addEventListener('mousemove', onMouseMove, { passive: true })
  window.addEventListener('pointermove', onWinPointerMove, { passive: true })
  window.addEventListener('pointerup', onWinPointerUp, { passive: true })
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onResize, { passive: true })

  rafId = requestAnimationFrame(loop)
})

onBeforeUnmount(() => {
  document.documentElement.classList.remove('db-landing-active')
  cancelAnimationFrame(rafId)
  clearTimeout(genTimer)
  revealIO && revealIO.disconnect()
  visIO && visIO.disconnect()
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('pointermove', onWinPointerMove)
  window.removeEventListener('pointerup', onWinPointerUp)
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div ref="rootEl" class="db-landing" @mouseover="onHoverCheck" @mouseleave="cursorMode = ''">
    <!-- shared SVG gradients -->
    <svg width="0" height="0" style="position:absolute" aria-hidden="true">
      <defs>
        <linearGradient id="g-wall" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#3a332a" /><stop offset="1" stop-color="#262019" />
        </linearGradient>
        <linearGradient id="g-floor" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#2b241d" /><stop offset="1" stop-color="#1a1611" />
        </linearGradient>
        <radialGradient id="g-glow">
          <stop offset="0" stop-color="#f3e2bb" stop-opacity=".9" /><stop offset="1" stop-color="#f3e2bb" stop-opacity="0" />
        </radialGradient>
        <linearGradient id="g-window" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#d9c79b" stop-opacity=".4" /><stop offset="1" stop-color="#8fa3bd" stop-opacity=".16" />
        </linearGradient>
        <linearGradient id="g-wood" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#6a563f" /><stop offset="1" stop-color="#4a3a2b" />
        </linearGradient>
        <linearGradient id="g-fabric" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#50607a" /><stop offset="1" stop-color="#3a4658" />
        </linearGradient>
        <linearGradient id="g-cream" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#d8cfc0" /><stop offset="1" stop-color="#b8ab97" />
        </linearGradient>
      </defs>
    </svg>

    <!-- ░░ loading screen ░░ -->
    <div v-if="!loaderGone" class="loader" :class="{ leaving: loaderLeaving }">
      <div class="loader-logo">Design<em>Bridge</em></div>
      <div class="loader-bar"></div>
    </div>

    <!-- ░░ custom cursor ░░ -->
    <div ref="dotEl" class="cursor-dot"></div>
    <div ref="ringEl" class="cursor-ring" :class="cursorMode">
      <span class="cursor-label">探索</span>
    </div>

    <!-- ░░ nav ░░ -->
    <header class="nav" :class="{ in: heroIn }">
      <a class="wordmark" href="#hero">Design<em>Bridge</em></a>
      <nav class="nav-links">
        <a href="#sec-rooms">看見可能</a>
        <a href="#sec-pipeline">協作流程</a>
        <a href="#sec-styles">風格示範</a>
        <RouterLink class="nav-cta" to="/">進入工作台</RouterLink>
      </nav>
    </header>

    <!-- ░░ 1 · hero ░░ -->
    <section id="hero" ref="heroEl" class="hero">
      <canvas v-if="!liteMode" ref="canvasEl" class="hero-canvas"></canvas>
      <div class="hero-inner">
        <p class="hero-eyebrow" :class="{ in: heroIn }">AI INTERIOR DESIGN SYSTEM</p>
        <h1 class="hero-title" :class="{ in: heroIn }">
          <span
            v-for="(ch, i) in heroChars"
            :key="i"
            class="char"
            :class="{ gold: goldChars.has(i) }"
            :style="{ transitionDelay: `${i * 30}ms` }"
          >{{ ch }}</span>
        </h1>
        <p class="hero-sub" :class="{ in: heroIn }">AI 理解語言、理解空間、理解你</p>
        <a class="hero-scroll" :class="{ in: heroIn }" href="#sec-rooms">
          <span class="scroll-line"><span class="scroll-dot"></span></span>
          向下探索
        </a>
      </div>
    </section>

    <!-- ░░ 2 · before / after ░░ -->
    <section id="sec-rooms" class="sec sec-rooms" data-reveal="rooms">
      <div class="sec-head slide-rotate" :class="{ in: revealed.has('rooms') }">
        <span class="sec-no">01</span>
        <h2>看見可能</h2>
        <p>拖曳分隔線，看 AI 如何把原始空間變成理想的家。</p>
      </div>
      <div class="ba-grid slide-rotate delay-1" :class="{ in: revealed.has('rooms') }">
        <article
          v-for="room in rooms"
          :key="room.id"
          class="ba-card"
          @mousemove="tilt"
          @mouseleave="untilt"
        >
          <div class="ba-stage" @pointerdown="baDown($event, room.id)">
            <div v-for="layer in ['before', 'after']" :key="layer" class="ba-layer" :class="layer"
              :style="layer === 'after' ? { clipPath: `inset(0 0 0 ${baPos[room.id]}%)` } : null">
              <svg class="room-svg" viewBox="0 0 400 280" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
                <rect width="400" height="198" fill="url(#g-wall)" />
                <rect y="198" width="400" height="82" fill="url(#g-floor)" />
                <rect y="196" width="400" height="3" fill="#171310" />
                <g v-if="room.id === 'living'">
                  <rect x="252" y="32" width="112" height="122" fill="#15110d" />
                  <rect x="258" y="38" width="100" height="110" fill="url(#g-window)" />
                  <line x1="308" y1="38" x2="308" y2="148" stroke="#15110d" stroke-width="4" />
                  <line x1="258" y1="93" x2="358" y2="93" stroke="#15110d" stroke-width="3" />
                  <circle cx="308" cy="90" r="46" fill="url(#g-glow)" opacity=".3" />
                  <rect x="58" y="48" width="48" height="62" fill="#1f1a14" stroke="#8a7350" stroke-width="2" />
                  <rect x="118" y="62" width="32" height="42" fill="#23282f" stroke="#8a7350" stroke-width="1.5" />
                  <ellipse cx="170" cy="244" rx="118" ry="20" fill="#352c22" opacity=".85" />
                  <rect x="84" y="132" width="156" height="34" rx="8" fill="url(#g-wood)" />
                  <rect x="76" y="158" width="172" height="38" rx="10" fill="#5a4a38" />
                  <rect x="92" y="142" width="56" height="26" rx="7" fill="url(#g-fabric)" />
                  <rect x="156" y="142" width="56" height="26" rx="7" fill="url(#g-cream)" />
                  <rect x="70" y="150" width="14" height="46" rx="6" fill="#4a3c2e" />
                  <rect x="240" y="150" width="14" height="46" rx="6" fill="#4a3c2e" />
                  <line x1="298" y1="196" x2="298" y2="112" stroke="#8a7350" stroke-width="3" />
                  <path d="M286 112 h24 l-5 -16 h-14 z" fill="#C9A96E" />
                  <circle cx="298" cy="116" r="24" fill="url(#g-glow)" opacity=".5" />
                  <rect x="28" y="174" width="24" height="22" rx="3" fill="#4a3c2e" />
                  <ellipse cx="40" cy="158" rx="16" ry="20" fill="#3f4a35" />
                  <ellipse cx="30" cy="166" rx="10" ry="13" fill="#46523b" />
                </g>
                <g v-else-if="room.id === 'bedroom'">
                  <rect x="38" y="34" width="92" height="112" fill="#15110d" />
                  <rect x="44" y="40" width="80" height="100" fill="url(#g-window)" />
                  <line x1="84" y1="40" x2="84" y2="140" stroke="#15110d" stroke-width="4" />
                  <circle cx="84" cy="86" r="40" fill="url(#g-glow)" opacity=".28" />
                  <line x1="262" y1="0" x2="262" y2="58" stroke="#8a7350" stroke-width="2" />
                  <path d="M250 58 h24 l-6 14 h-12 z" fill="#C9A96E" />
                  <circle cx="262" cy="72" r="20" fill="url(#g-glow)" opacity=".55" />
                  <rect x="150" y="112" width="176" height="48" rx="6" fill="#4a3c2e" />
                  <rect x="142" y="152" width="192" height="48" rx="8" fill="url(#g-wood)" />
                  <rect x="142" y="172" width="192" height="28" rx="6" fill="url(#g-fabric)" />
                  <rect x="160" y="128" width="56" height="22" rx="8" fill="url(#g-cream)" />
                  <rect x="246" y="128" width="56" height="22" rx="8" fill="url(#g-cream)" />
                  <rect x="96" y="164" width="36" height="36" rx="3" fill="#4a3c2e" />
                  <line x1="114" y1="150" x2="114" y2="164" stroke="#8a7350" stroke-width="2" />
                  <path d="M106 150 h16 l-4 -10 h-8 z" fill="#C9A96E" />
                  <circle cx="114" cy="146" r="14" fill="url(#g-glow)" opacity=".5" />
                  <ellipse cx="230" cy="246" rx="120" ry="18" fill="#352c22" opacity=".8" />
                </g>
                <g v-else>
                  <rect x="36" y="52" width="96" height="144" fill="#241d16" stroke="#171310" stroke-width="3" />
                  <line x1="36" y1="100" x2="132" y2="100" stroke="#171310" stroke-width="3" />
                  <line x1="36" y1="148" x2="132" y2="148" stroke="#171310" stroke-width="3" />
                  <rect x="44" y="72" width="10" height="26" fill="#705a3f" />
                  <rect x="57" y="66" width="9" height="32" fill="#44546e" />
                  <rect x="69" y="76" width="11" height="22" fill="#8a7350" />
                  <rect x="84" y="70" width="9" height="28" fill="#3f4a35" />
                  <rect x="98" y="74" width="12" height="24" fill="#5a4a38" />
                  <rect x="46" y="118" width="11" height="28" fill="#44546e" />
                  <rect x="60" y="124" width="9" height="22" fill="#705a3f" />
                  <rect x="74" y="116" width="10" height="30" fill="#8a7350" />
                  <rect x="90" y="122" width="9" height="24" fill="#3f4a35" />
                  <rect x="44" y="166" width="12" height="28" fill="#5a4a38" />
                  <rect x="60" y="172" width="9" height="22" fill="#8a7350" />
                  <rect x="73" y="164" width="10" height="30" fill="#44546e" />
                  <rect x="268" y="34" width="104" height="116" fill="#15110d" />
                  <rect x="274" y="40" width="92" height="104" fill="url(#g-window)" />
                  <line x1="320" y1="40" x2="320" y2="144" stroke="#15110d" stroke-width="4" />
                  <circle cx="320" cy="90" r="42" fill="url(#g-glow)" opacity=".28" />
                  <rect x="160" y="158" width="180" height="10" rx="3" fill="url(#g-wood)" />
                  <rect x="168" y="168" width="6" height="30" fill="#3a2f24" />
                  <rect x="326" y="168" width="6" height="30" fill="#3a2f24" />
                  <path d="M306 158 l-10 -24 l16 -8" stroke="#8a7350" stroke-width="3" fill="none" />
                  <circle cx="312" cy="126" r="6" fill="#C9A96E" />
                  <circle cx="312" cy="128" r="18" fill="url(#g-glow)" opacity=".55" />
                  <rect x="220" y="146" width="44" height="4" fill="#23282f" />
                  <path d="M226 146 l4 -18 h28 l4 18 z" fill="#2e3742" />
                  <rect x="196" y="184" width="46" height="8" rx="4" fill="#4a3c2e" />
                  <rect x="238" y="146" width="8" height="46" rx="4" fill="#4a3c2e" />
                  <line x1="218" y1="192" x2="218" y2="214" stroke="#3a2f24" stroke-width="5" />
                  <ellipse cx="218" cy="218" rx="22" ry="4" fill="#3a2f24" />
                  <ellipse cx="240" cy="250" rx="110" ry="14" fill="#352c22" opacity=".8" />
                </g>
              </svg>
              <div class="layer-tint"></div>
              <span class="ba-tag" :class="layer === 'before' ? 'left' : 'right'">
                {{ layer === 'before' ? '空拍原圖' : 'AI 設計結果' }}
              </span>
            </div>
            <div class="ba-divider" :style="{ left: `${baPos[room.id]}%` }">
              <div class="ba-handle">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="#0D0D0D" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9 6 L4 12 L9 18" /><path d="M15 6 L20 12 L15 18" />
                </svg>
              </div>
            </div>
          </div>
          <div class="ba-meta">
            <h3>{{ room.name }}</h3>
            <p>{{ room.desc }}</p>
          </div>
        </article>
      </div>
    </section>

    <!-- ░░ 3 · pipeline ░░ -->
    <section id="sec-pipeline" class="sec sec-pipeline" data-reveal="pipe">
      <div class="sec-head">
        <span class="sec-no">02</span>
        <h2 class="wordy" :class="{ in: revealed.has('pipe') }">
          <span v-for="(ch, i) in pipeHeadChars" :key="i" class="word" :style="{ transitionDelay: `${i * 60}ms` }">{{ ch }}</span>
        </h2>
        <p class="wordy-p" :class="{ in: revealed.has('pipe') }">
          <span v-for="(w, i) in pipeWords" :key="i" class="word" :style="{ transitionDelay: `${400 + i * 70}ms` }">{{ w }}</span>
        </p>
      </div>
      <div
        ref="pipeScrollEl"
        class="pipe-scroll"
        @pointerdown="pipeDragStart"
        @pointermove="pipeDragMove"
        @pointerup="pipeDragEnd"
        @pointerleave="pipeDragEnd"
      >
        <div class="pipe-inner">
          <svg class="pipe-svg" viewBox="0 0 1560 300" fill="none">
            <path ref="pipePathEl" class="pipe-path" :d="pipeD" />
            <g ref="packetEl" class="packet">
              <circle r="11" fill="url(#g-glow)" opacity=".7" />
              <circle r="4.5" fill="#C9A96E" />
            </g>
          </svg>
          <div
            v-for="(a, i) in agents"
            :key="a.name"
            class="agent-node"
            :class="{ open: openNode === i }"
            :style="{ left: `${a.x}px`, top: `${a.y + 120}px` }"
            @mouseenter="openNode = i"
            @mouseleave="openNode = -1"
            @click="openNode = openNode === i ? -1 : i"
          >
            <div class="node-core"><span>{{ String(i + 1).padStart(2, '0') }}</span></div>
            <div class="node-name">{{ a.name }}</div>
            <div class="agent-card">
              <h4>{{ a.name }} Agent</h4>
              <p>{{ a.desc }}</p>
            </div>
          </div>
        </div>
      </div>
      <p class="pipe-hint">← 拖曳探索完整流程 →</p>
    </section>

    <!-- ░░ 4 · style selector ░░ -->
    <section id="sec-styles" class="sec sec-styles" data-reveal="styles">
      <div class="sec-head cascade" :class="{ in: revealed.has('styles') }" style="--d: 0ms">
        <span class="sec-no">03</span>
        <h2>你的風格，精準呈現</h2>
        <p>選一種風格，看 AI 即時轉譯整個空間的語彙。</p>
      </div>
      <div class="style-tags cascade" :class="{ in: revealed.has('styles') }" style="--d: 80ms">
        <button
          v-for="(s, i) in styles"
          :key="s.id"
          :ref="(el) => setTagRef(el, i)"
          class="style-tag"
          :class="{ active: activeTagIdx === i }"
          @click="selectStyle(i)"
        >{{ s.label }}</button>
        <span class="tag-underline" :style="underlineStyle"></span>
      </div>
      <div class="demo-wrap cascade" :class="{ in: revealed.has('styles') }" style="--d: 160ms">
        <div class="demo-stage" :class="{ generating }">
          <svg class="room-svg" viewBox="0 0 400 280" preserveAspectRatio="xMidYMid slice" aria-hidden="true" :style="{ filter: displayedStyle.filter }">
            <rect width="400" height="198" fill="url(#g-wall)" />
            <rect y="198" width="400" height="82" fill="url(#g-floor)" />
            <rect y="196" width="400" height="3" fill="#171310" />
            <rect x="252" y="32" width="112" height="122" fill="#15110d" />
            <rect x="258" y="38" width="100" height="110" fill="url(#g-window)" />
            <line x1="308" y1="38" x2="308" y2="148" stroke="#15110d" stroke-width="4" />
            <line x1="258" y1="93" x2="358" y2="93" stroke="#15110d" stroke-width="3" />
            <circle cx="308" cy="90" r="46" fill="url(#g-glow)" opacity=".3" />
            <rect x="58" y="48" width="48" height="62" fill="#1f1a14" stroke="#8a7350" stroke-width="2" />
            <rect x="118" y="62" width="32" height="42" fill="#23282f" stroke="#8a7350" stroke-width="1.5" />
            <ellipse cx="170" cy="244" rx="118" ry="20" fill="#352c22" opacity=".85" />
            <rect x="84" y="132" width="156" height="34" rx="8" fill="url(#g-wood)" />
            <rect x="76" y="158" width="172" height="38" rx="10" fill="#5a4a38" />
            <rect x="92" y="142" width="56" height="26" rx="7" fill="url(#g-fabric)" />
            <rect x="156" y="142" width="56" height="26" rx="7" fill="url(#g-cream)" />
            <rect x="70" y="150" width="14" height="46" rx="6" fill="#4a3c2e" />
            <rect x="240" y="150" width="14" height="46" rx="6" fill="#4a3c2e" />
            <line x1="298" y1="196" x2="298" y2="112" stroke="#8a7350" stroke-width="3" />
            <path d="M286 112 h24 l-5 -16 h-14 z" fill="#C9A96E" />
            <circle cx="298" cy="116" r="24" fill="url(#g-glow)" opacity=".5" />
            <rect x="28" y="174" width="24" height="22" rx="3" fill="#4a3c2e" />
            <ellipse cx="40" cy="158" rx="16" ry="20" fill="#3f4a35" />
            <ellipse cx="30" cy="166" rx="10" ry="13" fill="#46523b" />
          </svg>
          <div class="stage-overlay" :style="{ background: displayedStyle.overlay }"></div>
          <div v-if="generating" class="shimmer"></div>
          <template v-if="!generating">
            <span
              v-for="(c, i) in displayedStyle.chips"
              :key="`${displayedStyle.id}-${i}`"
              class="chip"
              :class="`chip-p${i}`"
              :style="{ animationDelay: `${i * 90}ms` }"
            >{{ c }}</span>
          </template>
          <div class="stage-status">
            <span class="status-dot" :class="{ busy: generating }"></span>
            {{ generating ? 'AI 生成中…' : `${displayedStyle.label}・已生成` }}
          </div>
        </div>
      </div>
    </section>

    <!-- ░░ 5 · stats ░░ -->
    <section id="sec-stats" class="sec sec-stats" data-reveal="stats">
      <div class="stats-wipe" :class="{ in: revealed.has('stats') }">
      <div class="stats-bg"></div>
      <div class="sec-head center">
        <span class="sec-no">04</span>
        <h2>數字說話</h2>
      </div>
      <div class="stats-row">
        <div v-for="(s, i) in stats" :key="s.label" class="stat">
          <svg viewBox="0 0 180 180">
            <circle class="arc-track" cx="90" cy="90" r="84" />
            <circle
              class="arc"
              cx="90" cy="90" r="84"
              :style="{
                strokeDashoffset: statsOn ? 527.8 * (1 - s.frac) : 527.8,
                transitionDelay: `${i * 180}ms`,
              }"
            />
          </svg>
          <div class="stat-num">{{ counts[i] }}<span>{{ s.suffix }}</span></div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
      </div>
    </section>

    <!-- ░░ 6 · cta ░░ -->
    <section id="sec-cta" ref="ctaEl" class="sec sec-cta" data-reveal="cta" :class="{ in: revealed.has('cta') }">
      <div class="cta-dots" aria-hidden="true">
        <span v-for="i in CTA_DOT_COUNT" :key="i" :ref="(el) => setCtaDotRef(el, i - 1)" class="cta-dot"></span>
      </div>
      <p class="cta-kicker">你的理想空間，距離你只差一句話</p>
      <div ref="ctaBtnWrap" class="cta-btn-wrap">
        <button
          ref="ctaBtn"
          class="cta-btn"
          @mouseenter="ctaHover = true"
          @mouseleave="ctaHover = false"
          @click="goApp"
        >
          <span>開始體驗 DesignBridge</span>
        </button>
      </div>
      <div class="proof">
        <div class="avatars">
          <span v-for="i in 5" :key="i" class="av" :class="`av${i}`"></span>
        </div>
        已有 230 位設計師加入候補
      </div>
      <footer class="footer">© 2026 DesignBridge · AI Interior Design System</footer>
    </section>
  </div>
</template>

<!-- global: scrollbar, smooth scroll, page background while landing is mounted -->
<style>
html.db-landing-active {
  scroll-behavior: smooth;
  background: #0d0d0d;
  scrollbar-width: thin;
  scrollbar-color: #c9a96e #0d0d0d;
}
html.db-landing-active body { background: #0d0d0d; }
html.db-landing-active::-webkit-scrollbar { width: 7px; }
html.db-landing-active::-webkit-scrollbar-track { background: #0d0d0d; }
html.db-landing-active::-webkit-scrollbar-thumb {
  background: linear-gradient(#c9a96e, #8a7350);
  border-radius: 4px;
}
</style>

<style scoped>
/* ═══════════════ tokens & base ═══════════════ */
.db-landing {
  --bg: #0d0d0d;
  --gold: #c9a96e;
  --slate: #4a6fa5;
  --ink: #f0ede6;
  --ink-dim: rgba(240, 237, 230, 0.55);
  --glass: rgba(255, 255, 255, 0.04);
  --glass-edge: rgba(255, 255, 255, 0.08);
  --serif: 'Playfair Display', 'Noto Serif TC', serif;
  --sans: 'Inter', 'Noto Sans TC', sans-serif;

  background: var(--bg);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 16px;
  line-height: 1.7;
  overflow-x: clip;
  min-height: 100vh;
}
.db-landing :where(h1, h2, h3, h4) {
  font-family: var(--serif);
  font-weight: 600;
  line-height: 1.25;
  margin: 0;
}
.db-landing :where(p) { margin: 0; }
.db-landing :where(a) { color: inherit; text-decoration: none; }
.db-landing :where(button) {
  font: inherit;
  color: inherit;
  background: none;
  border: 0;
  padding: 0;
}
@media (pointer: fine) {
  .db-landing, .db-landing * { cursor: none; }
}

section { scroll-margin-top: 64px; }
.sec { position: relative; padding: 130px 6vw 110px; }

.sec-head { max-width: 680px; margin-bottom: 56px; }
.sec-head.center { margin-inline: auto; text-align: center; }
.sec-no {
  display: block;
  font-size: 12px;
  letter-spacing: 0.45em;
  color: var(--gold);
  margin-bottom: 14px;
  font-weight: 600;
}
.sec-head h2 { font-size: clamp(2rem, 4.4vw, 3.2rem); }
.sec-head p { margin-top: 16px; color: var(--ink-dim); font-size: 1.02rem; }

/* ═══════════════ loader ═══════════════ */
.loader {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: #0a0907;
  display: grid;
  place-content: center;
  gap: 18px;
  transition: transform 0.7s cubic-bezier(0.76, 0, 0.24, 1);
}
.loader.leaving { transform: translateY(-100%); }
.loader-logo {
  font-family: var(--serif);
  font-size: clamp(2rem, 6vw, 3.4rem);
  color: var(--ink);
  animation: loaderFade 1s ease both;
}
.loader-logo em { font-style: italic; color: var(--gold); }
.loader-bar {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--gold), transparent);
  transform-origin: center;
  animation: loaderBar 1.2s cubic-bezier(0.65, 0, 0.35, 1) both 0.15s;
}
@keyframes loaderFade { from { opacity: 0; transform: translateY(14px); } }
@keyframes loaderBar { from { transform: scaleX(0); } }

/* ═══════════════ custom cursor ═══════════════ */
.cursor-dot, .cursor-ring {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  z-index: 300;
  pointer-events: none;
  border-radius: 50%;
}
@media (pointer: fine) {
  .cursor-dot, .cursor-ring { display: block; }
}
.cursor-dot {
  width: 6px;
  height: 6px;
  background: var(--gold);
  box-shadow: 0 0 10px rgba(201, 169, 110, 0.9);
}
.cursor-ring {
  width: 32px;
  height: 32px;
  border: 1px solid rgba(201, 169, 110, 0.75);
  display: grid;
  place-content: center;
  transition:
    width 0.3s cubic-bezier(0.3, 1.4, 0.5, 1),
    height 0.3s cubic-bezier(0.3, 1.4, 0.5, 1),
    background-color 0.3s ease,
    border-color 0.3s ease;
}
.cursor-ring.hover {
  width: 56px;
  height: 56px;
  background: rgba(201, 169, 110, 0.18);
  border-color: var(--gold);
}
.cursor-ring.explore {
  width: 64px;
  height: 64px;
  background: rgba(13, 13, 13, 0.55);
  border-color: var(--gold);
  backdrop-filter: blur(2px);
}
.cursor-label {
  font-size: 12px;
  letter-spacing: 0.2em;
  color: var(--gold);
  opacity: 0;
  transition: opacity 0.25s ease;
}
.cursor-ring.explore .cursor-label { opacity: 1; }

/* ═══════════════ nav ═══════════════ */
.nav {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 5vw;
  background: rgba(13, 13, 13, 0.55);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--glass-edge);
  opacity: 0;
  transform: translateY(-12px);
  transition: opacity 0.7s ease 0.2s, transform 0.7s ease 0.2s;
}
.nav.in { opacity: 1; transform: none; }
.wordmark { font-family: var(--serif); font-size: 1.3rem; }
.wordmark em { font-style: italic; color: var(--gold); }
.nav-links { display: flex; align-items: center; gap: 30px; font-size: 0.88rem; }
.nav-links > a { color: var(--ink-dim); transition: color 0.25s ease; }
.nav-links > a:hover { color: var(--gold); }
.nav-cta {
  color: var(--gold) !important;
  border: 1px solid rgba(201, 169, 110, 0.5);
  padding: 7px 18px;
  border-radius: 999px;
  transition: background-color 0.25s ease, color 0.25s ease;
}
.nav-cta:hover { background: rgba(201, 169, 110, 0.14); }
@media (max-width: 768px) {
  .nav-links > a:not(.nav-cta) { display: none; }
}

/* ═══════════════ hero ═══════════════ */
.hero {
  position: relative;
  min-height: 100vh;
  display: grid;
  place-content: center;
  text-align: center;
  background:
    radial-gradient(900px 600px at 70% 20%, rgba(74, 111, 165, 0.10), transparent 65%),
    radial-gradient(800px 700px at 25% 80%, rgba(201, 169, 110, 0.08), transparent 60%),
    #0d0d0d;
  overflow: hidden;
}
.hero-canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.hero-inner { position: relative; padding: 0 6vw; }
.hero-eyebrow {
  font-size: 12px;
  letter-spacing: 0.55em;
  color: var(--slate);
  margin-bottom: 26px;
  opacity: 0;
  transition: opacity 1s ease 0.1s;
}
.hero-eyebrow.in { opacity: 1; }
.hero-title { font-size: clamp(2.5rem, 7.2vw, 5.2rem); letter-spacing: 0.04em; }
.hero-title .char {
  display: inline-block;
  opacity: 0;
  transform: translateY(0.55em);
  transition: opacity 0.7s cubic-bezier(0.2, 0.7, 0.3, 1), transform 0.7s cubic-bezier(0.2, 0.7, 0.3, 1);
}
.hero-title.in .char { opacity: 1; transform: none; }
.hero-title .char.gold {
  color: transparent;
  background: linear-gradient(160deg, #e8cf9e, var(--gold) 60%, #9b7d4e);
  -webkit-background-clip: text;
  background-clip: text;
}
.hero-sub {
  margin-top: 28px;
  font-size: clamp(1rem, 2vw, 1.2rem);
  color: var(--ink-dim);
  letter-spacing: 0.14em;
  opacity: 0;
  transform: translateY(14px);
  transition: opacity 0.9s ease 0.55s, transform 0.9s ease 0.55s;
}
.hero-sub.in { opacity: 1; transform: none; }
.hero-scroll {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-top: 72px;
  font-size: 11px;
  letter-spacing: 0.4em;
  color: var(--ink-dim);
  opacity: 0;
  transition: opacity 1s ease 1.1s;
}
.hero-scroll.in { opacity: 1; }
.scroll-line {
  position: relative;
  width: 1px;
  height: 52px;
  background: rgba(240, 237, 230, 0.18);
  overflow: hidden;
}
.scroll-dot {
  position: absolute;
  left: -1px;
  width: 3px;
  height: 10px;
  border-radius: 2px;
  background: var(--gold);
  animation: scrollDot 1.8s ease-in-out infinite;
}
@keyframes scrollDot {
  0% { transform: translateY(-12px); opacity: 0; }
  35% { opacity: 1; }
  100% { transform: translateY(56px); opacity: 0; }
}

/* ═══════════════ reveal primitives ═══════════════ */
.slide-rotate {
  opacity: 0;
  transform: perspective(1000px) translateX(-70px) rotateY(8deg);
  transition: opacity 0.9s cubic-bezier(0.2, 0.7, 0.3, 1), transform 0.9s cubic-bezier(0.2, 0.7, 0.3, 1);
}
.slide-rotate.delay-1 { transition-delay: 0.12s; }
.slide-rotate.in { opacity: 1; transform: none; }

.wordy .word, .wordy-p .word {
  display: inline-block;
  opacity: 0;
  transform: translateY(0.5em);
  transition: opacity 0.55s ease, transform 0.55s ease;
}
.wordy.in .word, .wordy-p.in .word { opacity: 1; transform: none; }
.wordy-p { margin-top: 16px; color: var(--ink-dim); font-size: 1.02rem; max-width: 560px; }

.cascade {
  opacity: 0;
  transform: translateY(34px);
  transition: opacity 0.75s ease var(--d, 0ms), transform 0.75s ease var(--d, 0ms);
}
.cascade.in { opacity: 1; transform: none; }

/* ═══════════════ section 2 · before / after ═══════════════ */
.sec-rooms { background: linear-gradient(180deg, #0d0d0d, #110f0c 30%, #110f0c); }
.ba-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
  gap: 28px;
}
.ba-card {
  background: var(--glass);
  border: 1px solid var(--glass-edge);
  border-radius: 18px;
  overflow: hidden;
  transform: perspective(900px) rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg)) translateY(var(--lift, 0));
  transition: transform 0.35s cubic-bezier(0.2, 0.7, 0.3, 1), box-shadow 0.35s ease;
  will-change: transform;
}
.ba-card:hover {
  --lift: -8px;
  box-shadow: 0 30px 60px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(201, 169, 110, 0.18);
}
.ba-stage {
  position: relative;
  aspect-ratio: 10 / 7;
  touch-action: pan-y;
  user-select: none;
  overflow: hidden;
}
.ba-layer { position: absolute; inset: 0; }
.room-svg { display: block; width: 100%; height: 100%; }
.ba-layer.before .room-svg { filter: grayscale(0.85) brightness(0.72) contrast(0.92); }
.ba-layer.before .layer-tint {
  position: absolute;
  inset: 0;
  background: linear-gradient(160deg, rgba(40, 44, 50, 0.35), rgba(13, 13, 13, 0.25));
}
.ba-layer.after .room-svg { filter: saturate(1.25) brightness(1.1); }
.ba-layer.after .layer-tint {
  position: absolute;
  inset: 0;
  background: linear-gradient(155deg, rgba(201, 169, 110, 0.16), rgba(74, 111, 165, 0.06) 70%);
}
.ba-tag {
  position: absolute;
  top: 12px;
  font-size: 11px;
  letter-spacing: 0.18em;
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(13, 13, 13, 0.62);
  border: 1px solid var(--glass-edge);
  backdrop-filter: blur(4px);
}
.ba-tag.left { left: 12px; color: rgba(240, 237, 230, 0.7); }
.ba-tag.right { right: 12px; color: var(--gold); border-color: rgba(201, 169, 110, 0.4); }
.ba-divider {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: linear-gradient(rgba(201, 169, 110, 0.1), var(--gold), rgba(201, 169, 110, 0.1));
}
.ba-handle {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--gold);
  display: grid;
  place-content: center;
  box-shadow: 0 0 22px rgba(201, 169, 110, 0.7);
  animation: handlePulse 2.4s ease-in-out infinite;
}
@keyframes handlePulse {
  0%, 100% { box-shadow: 0 0 14px rgba(201, 169, 110, 0.55); }
  50% { box-shadow: 0 0 30px rgba(201, 169, 110, 0.9); }
}
.ba-meta { padding: 18px 22px 22px; }
.ba-meta h3 { font-size: 1.25rem; }
.ba-meta p { margin-top: 6px; font-size: 0.9rem; color: var(--ink-dim); }

/* ═══════════════ section 3 · pipeline ═══════════════ */
.sec-pipeline { background: linear-gradient(180deg, #110f0c, #0e1014 35%, #0e1014); }
.pipe-scroll {
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: rgba(201, 169, 110, 0.5) transparent;
  cursor: grab;
  touch-action: pan-y;
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);
  mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);
}
.pipe-scroll::-webkit-scrollbar { height: 5px; }
.pipe-scroll::-webkit-scrollbar-thumb { background: rgba(201, 169, 110, 0.45); border-radius: 3px; }
.pipe-scroll:active { cursor: grabbing; }
.pipe-inner { position: relative; width: 1560px; height: 440px; }
.pipe-svg { position: absolute; left: 0; bottom: 0; width: 1560px; height: 300px; }
.pipe-path {
  stroke: rgba(201, 169, 110, 0.45);
  stroke-width: 1.6;
  stroke-dasharray: 7 9;
  animation: dashFlow 1.3s linear infinite;
}
@keyframes dashFlow { to { stroke-dashoffset: -16; } }
.packet circle:last-child { filter: drop-shadow(0 0 6px rgba(201, 169, 110, 0.95)); }
.agent-node {
  position: absolute;
  transform: translate(-50%, -50%);
  display: grid;
  justify-items: center;
  gap: 10px;
}
.node-core {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  display: grid;
  place-content: center;
  background: rgba(13, 13, 13, 0.85);
  border: 1px solid rgba(201, 169, 110, 0.55);
  font-family: var(--serif);
  font-size: 1.05rem;
  color: var(--gold);
  position: relative;
  transition: transform 0.3s cubic-bezier(0.3, 1.4, 0.5, 1), border-color 0.3s ease;
  animation: nodeGlow 3s ease-in-out infinite;
}
.agent-node:nth-child(odd) .node-core { animation-delay: -1.5s; }
@keyframes nodeGlow {
  0%, 100% { box-shadow: 0 0 12px rgba(201, 169, 110, 0.25); }
  50% { box-shadow: 0 0 26px rgba(201, 169, 110, 0.55); }
}
.node-core::after {
  content: '';
  position: absolute;
  inset: -7px;
  border-radius: 50%;
  border: 1px solid rgba(201, 169, 110, 0.3);
  animation: ripple 3s ease-out infinite;
}
@keyframes ripple {
  0% { transform: scale(0.85); opacity: 1; }
  70%, 100% { transform: scale(1.45); opacity: 0; }
}
.agent-node.open .node-core {
  transform: scale(1.18);
  border-color: var(--gold);
}
.node-name { font-size: 0.92rem; letter-spacing: 0.12em; color: var(--ink-dim); transition: color 0.3s ease; }
.agent-node.open .node-name { color: var(--ink); }
.agent-card {
  position: absolute;
  bottom: calc(100% + 16px);
  left: 50%;
  width: 250px;
  padding: 18px 20px;
  border-radius: 14px;
  background: rgba(20, 19, 16, 0.92);
  border: 1px solid rgba(201, 169, 110, 0.35);
  backdrop-filter: blur(10px);
  box-shadow: 0 24px 50px rgba(0, 0, 0, 0.5);
  opacity: 0;
  transform: translateX(-50%) translateY(12px) scale(0.94);
  transform-origin: bottom center;
  transition: opacity 0.35s ease, transform 0.35s cubic-bezier(0.3, 1.3, 0.5, 1);
  pointer-events: none;
  text-align: left;
}
.agent-node.open .agent-card { opacity: 1; transform: translateX(-50%) translateY(0) scale(1); }
.agent-card h4 { font-size: 1rem; color: var(--gold); }
.agent-card p { margin-top: 8px; font-size: 0.83rem; line-height: 1.65; color: var(--ink-dim); }
.pipe-hint {
  margin-top: 22px;
  text-align: center;
  font-size: 11px;
  letter-spacing: 0.35em;
  color: rgba(240, 237, 230, 0.35);
}

/* ═══════════════ section 4 · style selector ═══════════════ */
.sec-styles { background: linear-gradient(180deg, #0e1014, #120f0b 35%, #120f0b); }
.style-tags {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 28px;
  margin-bottom: 38px;
  padding-bottom: 12px;
}
.style-tag {
  font-size: 1rem;
  letter-spacing: 0.1em;
  color: var(--ink-dim);
  padding: 8px 2px;
  transition: color 0.3s ease;
}
.style-tag:hover { color: var(--ink); }
.style-tag.active { color: var(--gold); }
.tag-underline {
  position: absolute;
  bottom: 6px;
  height: 2px;
  border-radius: 2px;
  background: var(--gold);
  box-shadow: 0 0 12px rgba(201, 169, 110, 0.85);
  transition: left 0.45s cubic-bezier(0.65, 0, 0.35, 1), width 0.45s cubic-bezier(0.65, 0, 0.35, 1);
}
.demo-wrap { max-width: 880px; }
.demo-stage {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid var(--glass-edge);
  background: var(--glass);
}
.demo-stage .room-svg {
  width: 100%;
  height: 100%;
  transition: filter 0.8s ease;
}
.stage-overlay {
  position: absolute;
  inset: 0;
  transition: background 0.8s ease;
  pointer-events: none;
}
.shimmer {
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, transparent 32%, rgba(255, 255, 255, 0.13) 50%, transparent 68%);
  background-size: 220% 100%;
  animation: shimmerMove 0.6s linear infinite;
  backdrop-filter: blur(3px) saturate(0.7);
}
@keyframes shimmerMove { from { background-position: 180% 0; } to { background-position: -80% 0; } }
.chip {
  position: absolute;
  padding: 6px 14px;
  font-size: 12px;
  letter-spacing: 0.14em;
  border-radius: 999px;
  color: var(--ink);
  background: rgba(13, 13, 13, 0.66);
  border: 1px solid rgba(201, 169, 110, 0.45);
  backdrop-filter: blur(5px);
  animation: chipIn 0.55s cubic-bezier(0.3, 1.3, 0.5, 1) both;
}
@keyframes chipIn {
  from { opacity: 0; transform: translateY(14px) scale(0.85); }
}
.chip-p0 { top: 9%; left: 6%; }
.chip-p1 { top: 16%; right: 8%; }
.chip-p2 { bottom: 22%; left: 10%; }
.chip-p3 { bottom: 13%; right: 12%; }
.stage-status {
  position: absolute;
  bottom: 14px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 12px;
  letter-spacing: 0.2em;
  padding: 7px 18px;
  border-radius: 999px;
  background: rgba(13, 13, 13, 0.7);
  border: 1px solid var(--glass-edge);
  backdrop-filter: blur(6px);
  white-space: nowrap;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #7dba6f;
  box-shadow: 0 0 8px rgba(125, 186, 111, 0.8);
}
.status-dot.busy {
  background: var(--gold);
  box-shadow: 0 0 8px rgba(201, 169, 110, 0.9);
  animation: busyBlink 0.6s ease-in-out infinite alternate;
}
@keyframes busyBlink { to { opacity: 0.35; } }

/* ═══════════════ section 5 · stats ═══════════════ */
.sec-stats {
  text-align: center;
  padding: 0;
}
.stats-wipe {
  position: relative;
  background: #0a0908;
  overflow: hidden;
  padding: 130px 6vw 110px;
  clip-path: inset(100% 0 0 0);
  transition: clip-path 1s cubic-bezier(0.65, 0, 0.35, 1);
}
.stats-wipe.in { clip-path: inset(0 0 0 0); }
.stats-bg {
  position: absolute;
  inset: -20%;
  background:
    radial-gradient(620px circle at 30% 35%, rgba(201, 169, 110, 0.07), transparent 62%),
    radial-gradient(520px circle at 72% 65%, rgba(74, 111, 165, 0.07), transparent 60%);
  animation: bgDrift 16s ease-in-out infinite alternate;
  pointer-events: none;
}
@keyframes bgDrift {
  from { transform: translate(-3%, -2%); }
  to { transform: translate(3%, 3%); }
}
.stats-row {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: clamp(40px, 7vw, 110px);
  margin-top: 30px;
}
.stat { position: relative; width: 200px; padding: 36px 0; }
.stat svg {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 190px;
  height: 190px;
  transform: translate(-50%, -50%) rotate(-90deg);
}
.arc-track { fill: none; stroke: rgba(240, 237, 230, 0.07); stroke-width: 1.5; }
.arc {
  fill: none;
  stroke: var(--gold);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-dasharray: 527.8;
  filter: drop-shadow(0 0 5px rgba(201, 169, 110, 0.6));
  transition: stroke-dashoffset 1.8s cubic-bezier(0.5, 0, 0.2, 1);
}
.stat-num {
  font-family: var(--serif);
  font-size: clamp(2.8rem, 5vw, 3.8rem);
  color: var(--ink);
}
.stat-num span { color: var(--gold); }
.stat-label {
  margin-top: 6px;
  font-size: 0.85rem;
  letter-spacing: 0.3em;
  color: var(--ink-dim);
}

/* ═══════════════ section 6 · cta ═══════════════ */
.sec-cta {
  position: relative;
  min-height: 88vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  background:
    radial-gradient(700px 480px at 50% 42%, rgba(201, 169, 110, 0.09), transparent 65%),
    #0d0c0a;
  overflow: hidden;
  opacity: 0;
  transform: translateY(40px);
  transition: opacity 0.9s ease, transform 0.9s ease;
}
.sec-cta.in { opacity: 1; transform: none; }
.cta-dots { position: absolute; inset: 0; pointer-events: none; }
.cta-dot {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: rgba(201, 169, 110, 0.55);
  box-shadow: 0 0 7px rgba(201, 169, 110, 0.6);
}
.cta-kicker {
  font-size: clamp(1.05rem, 2.4vw, 1.4rem);
  letter-spacing: 0.22em;
  color: var(--ink-dim);
  margin-bottom: 44px;
}
.cta-btn-wrap { position: relative; }
.cta-btn {
  position: relative;
  overflow: hidden;
  font-family: var(--serif);
  font-size: clamp(1.2rem, 2.6vw, 1.6rem);
  letter-spacing: 0.08em;
  color: var(--ink);
  padding: 22px 58px;
  border-radius: 999px;
  border: 1px solid rgba(201, 169, 110, 0.6);
  background: rgba(201, 169, 110, 0.07);
  transition: transform 0.3s cubic-bezier(0.2, 0.7, 0.3, 1), box-shadow 0.4s ease, color 0.4s ease;
}
.cta-btn span { position: relative; z-index: 1; }
.cta-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, #9b7d4e, var(--gold) 50%, #e8cf9e);
  transform: translateX(-101%);
  transition: transform 0.55s cubic-bezier(0.65, 0, 0.35, 1);
}
.cta-btn:hover::before { transform: translateX(0); }
.cta-btn:hover {
  color: #161310;
  box-shadow: 0 0 50px rgba(201, 169, 110, 0.4);
}
.proof {
  margin-top: 46px;
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 0.88rem;
  color: var(--ink-dim);
}
.avatars { display: flex; }
.av {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 2px solid #0d0c0a;
  margin-left: -10px;
}
.av:first-child { margin-left: 0; }
.av1 { background: linear-gradient(135deg, #c9a96e, #8a6a3c); }
.av2 { background: linear-gradient(135deg, #4a6fa5, #2e4568); }
.av3 { background: linear-gradient(135deg, #a5836a, #6e5340); }
.av4 { background: linear-gradient(135deg, #7d8d7a, #4d5a4a); }
.av5 { background: linear-gradient(135deg, #b8946a, #5a4632); }
.footer {
  position: absolute;
  bottom: 26px;
  font-size: 11px;
  letter-spacing: 0.25em;
  color: rgba(240, 237, 230, 0.3);
}

/* ═══════════════ mobile & reduced motion ═══════════════ */
@media (max-width: 768px) {
  .sec { padding: 90px 6vw 80px; }
  .pipe-inner { height: 460px; }
  .agent-card { width: 210px; }
  .chip-p2, .chip-p3 { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .db-landing *, .db-landing *::before, .db-landing *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    transition-delay: 0ms !important;
  }
}
</style>
