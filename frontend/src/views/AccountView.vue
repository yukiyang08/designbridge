<script setup>
/**
 * 個人專區 — Figma MacBook Air - 14
 *
 * 設計稿的側欄只有「歷史設計 / 家具收藏」，白色主面板是空的。這裡補上第三項
 * 「家具查詢」：那是既有的 /furniture 頁，舊版靠工作台的浮動按鈕進入，新版工作台
 * 沒有浮動按鈕了，不給它一個入口就會變成沒人找得到的孤兒頁。
 */
import { RouterLink } from 'vue-router'
import AppNav from '@/components/shell/AppNav.vue'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import sceneBg from '@/assets/figma/room-bg.png'

const { selectedCount } = useFurnitureSelection()

const SECTIONS = [
  {
    to: '/history',
    label: '歷史設計',
    desc: '過去每一次生成的渲染圖、風格參數與需求解析，可檢視細節或批次刪除。',
  },
  {
    to: '/cart',
    label: '家具收藏',
    desc: '在估價與家具查詢中收藏的商品，集中在這裡對照價格與購買連結。',
  },
  {
    to: '/furniture',
    label: '家具查詢',
    desc: '依分類與關鍵字搜尋 IKEA 台灣商品資料庫，可直接加入收藏。',
  },
]
</script>

<template>
  <div class="db-scene account" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <AppNav />

    <div class="db-card account-card">
      <aside class="side">
        <RouterLink
          v-for="s in SECTIONS" :key="s.to"
          :to="s.to"
          class="side-item"
        >
          {{ s.label }}
          <span v-if="s.to === '/cart' && selectedCount" class="count">{{ selectedCount }}</span>
        </RouterLink>
      </aside>

      <main class="main">
        <h1 class="title">個人專區</h1>
        <p class="lead">你的設計紀錄與收藏都在這裡。</p>

        <div class="cards">
          <RouterLink v-for="s in SECTIONS" :key="s.to" :to="s.to" class="entry">
            <h2>
              {{ s.label }}
              <span v-if="s.to === '/cart' && selectedCount" class="count">{{ selectedCount }}</span>
            </h2>
            <p>{{ s.desc }}</p>
            <span class="go">前往 →</span>
          </RouterLink>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.account { display: flex; flex-direction: column; padding-bottom: 3rem; }

.account-card {
  display: grid;
  grid-template-columns: 210px 1fr;
  min-height: 560px;
  margin-top: 1.25rem;
  overflow: hidden;
}

/* 設計稿的側欄是白底、純文字連結 */
.side {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 2rem 1rem;
  border-right: 1px solid #efefef;
}
.side-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.85rem;
  border-radius: var(--db-radius-chip);
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.1rem;
  text-decoration: none;
  transition: background 0.16s, color 0.16s;
}
.side-item:hover { background: var(--db-chip-soft); }
.side-item.router-link-active { background: var(--db-accent); color: var(--db-on-accent); }

.main { padding: 2.5rem clamp(1.5rem, 3vw, 2.75rem); }

.title {
  margin: 0 0 0.4rem;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.9rem;
  color: var(--db-text);
}
.lead { margin: 0 0 2rem; color: var(--db-text-soft); }

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1.25rem;
}

.entry {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1.35rem;
  border: 2px solid #ececec;
  border-radius: var(--db-radius-chip);
  color: inherit;
  text-decoration: none;
  transition: border-color 0.16s, transform 0.16s, box-shadow 0.16s;
}
.entry:hover {
  border-color: var(--db-accent);
  transform: translateY(-3px);
  box-shadow: var(--db-shadow-soft);
}
.entry h2 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.2rem;
}
.entry p {
  margin: 0;
  flex: 1;
  font-size: 0.86rem;
  line-height: 1.7;
  color: var(--db-text-soft);
}
.go { color: var(--db-accent-deep); font-size: 0.85rem; }

.count {
  display: inline-grid;
  place-items: center;
  min-width: 20px; height: 20px;
  padding: 0 6px;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-family: var(--db-font-body);
  font-style: normal;
  font-size: 0.7rem;
}
.side-item.router-link-active .count { background: #fff; color: var(--db-accent-deep); }

@media (max-width: 780px) {
  .account-card { grid-template-columns: 1fr; }
  .side {
    flex-direction: row;
    overflow-x: auto;
    border-right: none;
    border-bottom: 1px solid #efefef;
    padding: 1rem;
  }
  .side-item { white-space: nowrap; }
}
@media (prefers-reduced-motion: reduce) {
  .entry:hover { transform: none; }
}
</style>
