<script setup>
/** Figma MacBook Air - 9：三個設計入口；平面圖入口再分一層（?from=plan）選上傳或自動生成。 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppNav from '@/components/shell/AppNav.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import sceneBg from '@/assets/figma/room-bg.png'
import thumbPlan from '@/assets/figma/entry-plan-3d.jpg'
import planAuto from '@/assets/figma/entry-plan.png'   // CAD 工具自動生成的平面圖，就是這條路的產出
import thumbPhoto from '@/assets/figma/entry-photo.png'
import thumbScratch from '@/assets/figma/entry-scratch.png'

const route = useRoute()
const router = useRouter()
const { startFlow } = useDesignFlow()

const ICON_UPLOAD = 'M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3'
const ICON_GRID = 'M4 4h16v16H4zM4 13h8M12 4v16M12 9h8'

const ENTRIES = [
  { source: 'plan', thumb: thumbPlan, title: '從平面圖開始', desc: '照真實格局逐間規劃，家具尺寸對得上', cta: '開始規劃' },
  { source: 'photo', thumb: thumbPhoto, title: '改造現有空間', desc: '上傳房間照片，保留格局看翻新後的樣子', cta: '上傳空間照片' },
  { source: 'skip', thumb: thumbScratch, title: '從想法開始', desc: '描述你想要的空間，不排家具直接出圖', cta: '描述設計需求' },
]
// 上傳與自動生成的輸入完全不同（上傳會跳過房型表單），進流程前就分開，不讓想上傳的人先看到表單
const PLAN_CHOICES = [
  { source: 'upload', icon: ICON_UPLOAD, img: thumbPlan, crop: true, title: '上傳我的平面圖', desc: '已經有平面圖：AI 辨識房間與尺寸，照你家的格局規劃', cta: '上傳平面圖' },
  { source: 'cad', icon: ICON_GRID, img: planAuto, title: '自動生成格局', desc: '還沒有平面圖：填房型與坪數，自動切出整層格局', cta: '開始填寫' },
]

// 用 query 而不是元件狀態：瀏覽器上一頁能回到三張卡
const planLevel = computed(() => route.query.from === 'plan')

function pick(source) {
  if (source === 'plan') return router.push({ query: { from: 'plan' } })
  startFlow(source)
  router.push('/studio')
}
</script>

<template>
  <div class="db-scene start" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />

    <template v-if="!planLevel">
      <header class="intro">
        <h1 class="prompt">讓理想空間，從這裡開始</h1>
        <p class="lead">從平面圖、現有空間或一個想法出發，一步步做出你的家。</p>
      </header>

      <div class="cards">
        <button v-for="e in ENTRIES" :key="e.source" type="button" class="entry" @click="pick(e.source)">
          <div class="thumb-wrap">
            <img :src="e.thumb" alt="" class="thumb" />
          </div>
          <div class="body">
            <h2 class="title">{{ e.title }}</h2>
            <p class="desc">{{ e.desc }}</p>
            <!-- 整張卡已是 button，這裡只是視覺上的連結 -->
            <div class="links"><span class="link" aria-hidden="true">{{ e.cta }} <span>→</span></span></div>
          </div>
        </button>
      </div>
    </template>

    <template v-else>
      <header class="intro">
        <h1 class="prompt">你手上有平面圖嗎？</h1>
        <p class="lead">兩種都會做出整層格局，之後逐間設計。</p>
      </header>

      <div class="cards cards--two">
        <button v-for="c in PLAN_CHOICES" :key="c.source" type="button" class="entry" @click="pick(c.source)">
          <div class="icon-thumb" aria-hidden="true">
            <img v-if="c.img" :src="c.img" alt="" :class="['choice-img', { 'choice-img--blueprint': c.crop }]" />
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path :d="c.icon" /></svg>
          </div>
          <div class="body">
            <h2 class="title">{{ c.title }}</h2>
            <p class="desc">{{ c.desc }}</p>
            <div class="links"><span class="link" aria-hidden="true">{{ c.cta }} <span>→</span></span></div>
          </div>
        </button>
      </div>
      <button type="button" class="back" @click="router.replace({ query: {} })">
        <span aria-hidden="true">←</span> 重新選擇模式
      </button>
    </template>
  </div>
</template>


<style scoped>
.start {
  display: flex;
  flex-direction: column;
  padding-bottom: 3rem;
}
/* 卡片內也是室內照：背景輕微模糊退到後面；inset 負值藏住模糊的淡邊 */
.start::before { inset: -16px; filter: blur(4px); }

.intro {
  margin: clamp(1rem, 4vh, 2.75rem) auto clamp(1.5rem, 4vh, 2.5rem);
  padding: 0 1.5rem;
  text-align: center;
  color: #fff;
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.42);
}
.prompt {
  margin: 0 0 0.5rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.75rem, 3.6vw, 2.9rem);
  text-wrap: balance;
}
.lead { margin: 0; font-size: clamp(0.95rem, 1.3vw, 1.1rem); opacity: 0.92; }

.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: clamp(1rem, 2vw, 1.75rem);
  width: min(1240px, calc(100vw - 3rem), 150vh);   /* 4:3 圖較高，矮螢幕也要一屏看完 */
  margin: 0 auto;
}

.entry {
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
  border: none;
  border-radius: 14px;
  background: var(--db-card);
  box-shadow: var(--db-shadow-soft);
  color: var(--db-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}
button.entry:hover { transform: translateY(-4px); box-shadow: var(--db-shadow-card); }
.entry:focus-visible, .link:focus-visible {
  outline: 3px solid var(--db-accent);
  outline-offset: 3px;
}

.thumb-wrap { overflow: hidden; }
.thumb {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;   /* 三張縮圖同尺寸，不看原圖比例 */
  object-fit: cover;
  transition: transform 0.4s;
}
button.entry:hover .thumb { transform: scale(1.03); }

.body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.35rem;
  padding: 1.1rem 1.4rem 1.3rem;
}
.title {
  margin: 0;
  font-family: var(--db-font-display);
  font-weight: 500;
  font-size: clamp(1.2rem, 1.6vw, 1.5rem);
  line-height: 1.4;
}
.desc { margin: 0; font-size: 0.9rem; line-height: 1.65; color: var(--db-text-soft); }

/* 連結貼卡底，三張卡的動作列對齊 */
.links { display: flex; flex-wrap: wrap; gap: 0.25rem 1.5rem; margin-top: auto; padding-top: 0.9rem; }
.link {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 44px;
  padding: 0;
  border: none;
  background: none;
  color: var(--db-accent-ink);
  font: inherit;
  font-weight: 500;
  white-space: nowrap;   /* 箭頭不能被擠到下一行 */
  cursor: pointer;
}
/* 第二層：上傳／自動生成兩大格，圖區改放大圖示 */
.cards--two { grid-template-columns: repeat(2, minmax(0, 1fr)); width: min(880px, calc(100vw - 3rem)); }
.icon-thumb {
  display: grid;
  place-items: center;
  aspect-ratio: 16 / 9;
  background: var(--db-paper);
  border-bottom: 1px solid var(--db-line);
  color: var(--db-accent-ink);
}
.icon-thumb svg { width: 72px; height: 72px; transition: transform 0.3s; }
button.entry:hover .icon-thumb svg { transform: scale(1.08); }
/* 平面圖線條貼邊，裁掉會缺一塊：完整放進白底 */
.choice-img { position: absolute; inset: 0; width: 100%; height: 100%; padding: 0.75rem; object-fit: contain; background: #fff; }
.icon-thumb { position: relative; overflow: hidden; }
/* 上傳：只取 3D 圖左下的 2D 藍圖那塊，代表「你手上的平面圖」 */
.choice-img--blueprint { padding: 0; object-fit: cover; object-position: 0 75%; transform: scale(1.8); transform-origin: 0 70%; }
.back {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 44px;
  margin: 1.25rem auto 0;
  padding: 0 1rem;
  border: none;
  background: none;
  color: #fff;
  font: inherit;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.5);
  cursor: pointer;
}
.back:hover { text-decoration: underline; text-underline-offset: 0.3em; }
.back:focus-visible { outline: 3px solid #fff; outline-offset: 2px; }
.link span { transition: transform 0.18s; }
.link:hover span, button.entry:hover .link span { transform: translateX(4px); }
.link:hover { text-decoration: underline; text-underline-offset: 0.3em; }

@media (max-width: 900px) {
  .cards, .cards--two { grid-template-columns: 1fr; width: min(560px, calc(100vw - 2rem)); }
  .thumb { aspect-ratio: 16 / 9; }
}
@media (prefers-reduced-motion: reduce) {
  button.entry:hover, button.entry:hover .thumb, button.entry:hover .icon-thumb svg, .link span { transform: none !important; }
}
/* 手機：卡片改成橫向小列（縮圖在左、文字在右），一屏看得到全部入口 */
@media (max-width: 640px) {
  .prompt { font-size: 1.5rem; }
  .cards { gap: 0.75rem; }
  .entry { flex-direction: row; align-items: stretch; }
  .thumb-wrap { flex: none; width: 104px; }
  .thumb { height: 100%; aspect-ratio: auto; }
  .body { padding: 0.8rem 1rem; gap: 0.15rem; }
  .title { font-size: 1.1rem; }
  .desc { font-size: 0.8rem; line-height: 1.5; }
  .links { padding-top: 0.2rem; }
  .icon-thumb { flex: none; width: 104px; aspect-ratio: auto; border-bottom: none; }
  .icon-thumb svg { width: 40px; height: 40px; }
}
</style>
