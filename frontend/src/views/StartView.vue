<script setup>
/** Figma MacBook Air - 9：你想從哪裡開始設計？三張入口卡。 */
import { useRouter } from 'vue-router'
import AppNav from '@/components/shell/AppNav.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'
import sceneBg from '@/assets/figma/room-bg.png'
import thumbPlan from '@/assets/figma/entry-plan.png'
import thumbPhoto from '@/assets/figma/entry-photo.png'
import thumbScratch from '@/assets/figma/entry-scratch.png'

const router = useRouter()
const { startFlow } = useDesignFlow()

const ICON_UPLOAD = 'M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3'
const ICON_GRID = 'M4 4h16v16H4zM4 13h8M12 4v16M12 9h8'

// 上傳與自動生成的輸入完全不同（上傳會跳過房型表單），在入口就分開，不讓想上傳的人先看到表單
const ENTRIES = [
  {
    source: 'cad',
    thumb: thumbPlan,
    title: ['整層平面圖，', '從格局開始逐間設計'],
    desc: '有平面圖就上傳讓 AI 辨識房間；沒有的話填房型＋坪數自動切出格局',
    actions: [
      { source: 'upload', label: '上傳我的平面圖', icon: ICON_UPLOAD },
      { source: 'cad', label: '自動生成格局', icon: ICON_GRID },
    ],
  },
  {
    source: 'photo',
    thumb: thumbPhoto,
    title: ['我是租屋族，', '要改變現有空間'],
    desc: '拍一張現況照，AI 讀懂格局後直接改造成你要的樣子',
  },
  {
    source: 'skip',
    thumb: thumbScratch,
    title: ['從零開始，', '直接描述你的理想空間'],
    desc: '不排家具，只用一段描述加風格參考直接生成效果圖',
  },
]

function pick(source) {
  startFlow(source)
  router.push('/studio')
}
</script>

<template>
  <div class="db-scene start" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />

    <h1 class="prompt">你想從哪裡開始設計？</h1>

    <div class="cards">
      <!-- 有兩個動作的卡片不能整張可點（button 裡不能再放 button），改成 div＋兩顆按鈕 -->
      <component
        :is="e.actions ? 'div' : 'button'"
        v-for="e in ENTRIES"
        :key="e.source"
        :type="e.actions ? undefined : 'button'"
        :class="['entry', { 'entry--split': e.actions }]"
        @click="!e.actions && pick(e.source)"
      >
        <div class="thumb-wrap">
          <img :src="e.thumb" alt="" :class="['thumb', { 'thumb--contain': e.thumb === thumbPlan }]" />
        </div>
        <h2 class="title">
          <span v-for="line in e.title" :key="line">{{ line }}</span>
        </h2>
        <p class="desc">{{ e.desc }}</p>
        <div v-if="e.actions" class="split-actions">
          <button v-for="a in e.actions" :key="a.source" type="button" class="split-btn" @click="pick(a.source)">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="a.icon" /></svg>
            {{ a.label }}
          </button>
        </div>
      </component>
    </div>
  </div>
</template>

<style scoped>
.start {
  display: flex;
  flex-direction: column;
  padding-bottom: 3rem;
}

.prompt {
  margin: clamp(1rem, 4vh, 2.75rem) 0 clamp(1.5rem, 4vh, 2.5rem);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.75rem, 3.9vw, 3.125rem);
  color: #fff;
  text-align: center;
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.42);
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: clamp(1rem, 2.4vw, 2rem);
  width: min(1440px, calc(100vw - 3rem));
  margin: 0 auto;
}

.entry {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
  padding: 2.5rem 1.5rem 2rem;
  border: 2px solid transparent;
  border-radius: var(--db-radius-card);
  background: var(--db-card);
  box-shadow: var(--db-shadow-card);
  cursor: pointer;
  text-align: center;
  transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
}
button.entry:hover {
  transform: translateY(-6px);
  border-color: var(--db-accent);
  box-shadow: 0 24px 56px rgba(28, 24, 18, 0.24);
}
.entry:focus-visible, .split-btn:focus-visible {
  outline: 3px solid var(--db-accent);
  outline-offset: 3px;
}
.entry--split { cursor: default; }

.split-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
  width: 100%;
}
.split-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  min-height: 44px;
  padding: 0.85rem 0.5rem;
  border: 2px solid #e2ddd0;
  border-radius: 12px;
  background: #fff;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-weight: 500;
  font-size: 1rem;
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s, transform 0.14s;
}
.split-btn:hover {
  border-color: var(--db-accent);
  background: var(--db-accent-soft);
  transform: translateY(-2px);
}

.thumb-wrap {
  display: grid;
  place-items: center;
  width: 100%;
  flex: 1;
  min-height: 190px;
}
.thumb {
  width: 100%;
  aspect-ratio: 3 / 2;   /* 三張縮圖同尺寸，不看原圖比例 */
  border-radius: 12px;
  object-fit: cover;
}
.thumb--contain { object-fit: contain; }   /* 平面圖的線條貼邊，裁掉會缺一塊 */

.title {
  display: flex;
  flex-direction: column;
  margin: 0;
  font-family: var(--db-font-display);
  font-style: normal;
  font-weight: 500;
  font-size: clamp(1.15rem, 1.7vw, 1.6rem);
  line-height: 1.4;
  color: var(--db-text);
}

/* 設計稿只有標題。加一行說明，是因為「從零開始」和「上傳照片」光看標題
   分不出實際差在哪（一個排家具、一個不排），使用者選錯要重跑一次生成。 */
.desc {
  margin: 0;
  max-width: 30ch;
  font-size: 0.88rem;
  line-height: 1.65;
  color: var(--db-text-soft);
}

/* 4 張卡在筆電寬度以下會太擠，先降成 2x2，太窄（手機）再收成單欄 */
@media (max-width: 1180px) {
  .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); width: min(720px, calc(100vw - 3rem)); }
}
@media (max-width: 900px) {
  .cards { grid-template-columns: 1fr; width: min(560px, calc(100vw - 2rem)); }
  .thumb-wrap { min-height: 0; }
  .thumb { max-height: 180px; }
}
@media (prefers-reduced-motion: reduce) {
  button.entry:hover, .split-btn:hover { transform: none; }
}
/* 手機：三張大卡改成橫向小列（縮圖在左、標題與說明在右），一屏看得到全部入口 */
@media (max-width: 640px) {
  .prompt { padding: 0 1rem; font-size: 1.5rem; }
  .cards { gap: 0.75rem; }
  .entry {
    display: grid;
    grid-template-columns: 96px 1fr;
    grid-template-areas: "t h" "t d";
    align-items: center;
    gap: 0.2rem 1rem;
    padding: 0.9rem 1rem;
    text-align: left;
  }
  .thumb-wrap { grid-area: t; min-height: 0; }
  .thumb { max-height: 80px; }
  .title { grid-area: h; flex-direction: row; flex-wrap: wrap; column-gap: 0.3rem; font-size: 1.1rem; }
  .desc {
    grid-area: d; max-width: none; font-size: 0.8rem; line-height: 1.5;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .entry--split { grid-template-areas: "t h" "t d" "a a"; }
  .split-actions { grid-area: a; margin-top: 0.6rem; }
  .split-btn { flex-direction: row; padding: 0.6rem 0.5rem; font-size: 0.92rem; }
}
</style>
