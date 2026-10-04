<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
/** 設計稿沒有畫載入狀態，但每個生成步驟都要等 10–60 秒，沒有它畫面會像當掉。 */
defineProps({
  title: { type: String, default: 'AI 生成中' },
  sub:   { type: String, default: '' },
})

// 等 10–60 秒的步驟，讓人看到時間在走，才知道不是當掉。
const elapsed = ref(0)
let timer
onMounted(() => { timer = setInterval(() => elapsed.value++, 1000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div class="loading-state">
    <div class="ring">
      <div class="spinner"></div>
      <div class="mark">✦</div>
    </div>
    <p class="title">{{ title }}</p>
    <p v-if="sub" class="sub">{{ sub }}</p>
    <p v-if="elapsed >= 3" class="elapsed" aria-live="off">已等待 {{ elapsed }} 秒</p>
  </div>
</template>

<style scoped>
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  min-height: 380px;
  padding: 3rem 1.5rem;
  text-align: center;
}

.ring {
  position: relative;
  width: 78px;
  height: 78px;
  margin-bottom: 1rem;
}
.spinner {
  position: absolute;
  inset: 0;
  border: 3px solid var(--db-chip-soft);
  border-top-color: var(--db-accent);
  border-radius: 50%;
  animation: spin 0.95s linear infinite;
}
.mark {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--db-accent);
  font-size: 1.5rem;
  animation: pulse 1.8s ease-in-out infinite;
}
@keyframes spin  { to { transform: rotate(360deg); } }
@keyframes pulse { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }

.title {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.4rem;
  color: var(--db-text);
}
.elapsed {
  margin: 0.5rem 0 0;
  color: var(--db-secondary);
  font-family: var(--db-font-num);
  font-size: 0.85rem;
  letter-spacing: 0.04em;
}
.sub {
  margin: 0;
  color: var(--db-text-soft);
  font-size: 0.95rem;
}

@media (prefers-reduced-motion: reduce) {
  .spinner, .mark { animation: none; }
}
</style>
