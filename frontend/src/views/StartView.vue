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

// 設計稿只畫三張卡。第四條路（上傳 2D 平面配置圖）後端與 useDesignFlow 都還在，
// 要重新開放時在這裡補一筆 { source: 'upload', ... } 就會接回流程。
const ENTRIES = [
  {
    source: 'generate',
    thumb: thumbPlan,
    title: ['從繪製平面設計圖開始'],
    desc: '選房型與家具，AI 先排出 2D 平面配置，可自己拖曳微調',
  },
  {
    source: 'photo',
    thumb: thumbPhoto,
    title: ['上傳現有空間照片'],
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
      <button
        v-for="e in ENTRIES"
        :key="e.source"
        type="button"
        class="entry"
        @click="pick(e.source)"
      >
        <div class="thumb-wrap">
          <img :src="e.thumb" :alt="e.title.join('')" class="thumb" />
        </div>
        <h2 class="title">
          <span v-for="line in e.title" :key="line">{{ line }}</span>
        </h2>
        <p class="desc">{{ e.desc }}</p>
      </button>
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
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: clamp(1rem, 2.4vw, 2rem);
  width: min(1186px, calc(100vw - 3rem));
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
.entry:hover {
  transform: translateY(-6px);
  border-color: var(--db-accent);
  box-shadow: 0 24px 56px rgba(28, 24, 18, 0.24);
}
.entry:focus-visible {
  outline: 3px solid var(--db-accent);
  outline-offset: 3px;
}

.thumb-wrap {
  display: grid;
  place-items: center;
  width: 100%;
  flex: 1;
  min-height: 190px;
}
.thumb {
  max-width: 100%;
  max-height: 230px;
  object-fit: contain;
}

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

@media (max-width: 900px) {
  .cards { grid-template-columns: 1fr; width: min(560px, calc(100vw - 2rem)); }
  .thumb-wrap { min-height: 0; }
  .thumb { max-height: 180px; }
}
@media (prefers-reduced-motion: reduce) {
  .entry:hover { transform: none; }
}
</style>
