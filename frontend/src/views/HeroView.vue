<script setup>
/** Figma MacBook Air - 5：滿版室內照 + 標語 + 開始設計。 */
import { useRouter } from 'vue-router'
import AppNav from '@/components/shell/AppNav.vue'
import heroBg from '@/assets/figma/room-bg.png'

const router = useRouter()
</script>

<template>
  <div class="hero" :style="{ '--hero-image': `url(${heroBg})` }">
    <AppNav />

    <div class="hero-body">
      <h1 class="headline">
        <span>你的想像，</span>
        <span>我們幫你變成現實</span>
      </h1>
      <button class="start-btn" @click="router.push('/start')">開始設計</button>
    </div>
  </div>
</template>

<style scoped>
.hero {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--db-ink);
  font-family: var(--db-font-body);
  overflow: hidden;
}
/* 設計稿：照片 opacity 60% 疊在 #313131 上 */
.hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--hero-image) center / cover no-repeat;
  opacity: 0.6;
}
.hero > * { position: relative; }

.hero-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  gap: 3.5rem;
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

.start-btn {
  min-width: 211px;
  padding: 0.85rem 2.5rem;
  border: none;
  border-radius: var(--db-radius-chip);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: clamp(1.25rem, 2vw, 1.875rem);
  cursor: pointer;
  transition: background 0.18s, transform 0.14s, box-shadow 0.18s;
}
.start-btn:hover {
  background: var(--db-accent-deep);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.32);
  transform: translateY(-2px);
}
.start-btn:active { transform: translateY(0); }

@media (max-width: 720px) {
  .hero-body { gap: 2.25rem; padding-bottom: 4rem; }
}
@media (prefers-reduced-motion: reduce) {
  .start-btn { transition: background 0.18s; }
  .start-btn:hover { transform: none; }
}
</style>
