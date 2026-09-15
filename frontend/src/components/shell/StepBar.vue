<script setup>
/**
 * Figma 的流程列：`01 空間設定  02 繪製平面圖  03 3D渲染圖 …`
 * 圓圈在設計稿是純色 ellipse（進行中 #CDC5AC、其餘 #D9D9D9），
 * 沒有向量細節，所以用 CSS 圓形，不另外掛 SVG 檔。
 *
 * 步數依入口路徑而定（見 useDesignFlow 的 STEP_FLOWS），不是寫死六步。
 */
defineProps({
  steps:   { type: Array,  required: true },   // [{ key, label }]
  current: { type: Number, default: 0 },
  // 只允許回頭點已經走過的步驟，避免跳過還沒產生資料的步驟造成空白畫面
  maxReached: { type: Number, default: 0 },
})

const emit = defineEmits(['go'])
</script>

<template>
  <ol class="step-bar">
    <li
      v-for="(s, i) in steps"
      :key="s.key"
      :class="['step', { active: i === current, reachable: i <= maxReached }]"
    >
      <button
        type="button"
        class="step-hit"
        :disabled="i > maxReached"
        :aria-current="i === current ? 'step' : undefined"
        @click="i <= maxReached && emit('go', i)"
      >
        <span class="dot">{{ String(i + 1).padStart(2, '0') }}</span>
        <span class="label">{{ s.label }}</span>
      </button>
    </li>
  </ol>
</template>

<style scoped>
.step-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.6rem;
  margin: 0;
  padding: 0.5rem 1.5rem 1.25rem;
  list-style: none;
}

.step-hit {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.2rem 0.35rem;
  border: none;
  border-radius: var(--db-radius-pill);
  background: none;
  cursor: pointer;
  transition: opacity 0.16s;
}
.step-hit:disabled { cursor: default; }
.step:not(.active) .step-hit:not(:disabled):hover { opacity: 0.78; }

.dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--db-chip);
  color: var(--db-on-accent);
  font-family: var(--db-font-num);
  font-size: 1.35rem;
  line-height: 1;
  flex-shrink: 0;
}

.label {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.35rem;
  color: #fff;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.5);
  white-space: nowrap;
}

/* 只有進行中那一步變色（圓圈 + 標籤）。已完成的步驟不上色——同時有兩三個
   米色圓圈時看不出「現在在哪一步」，那正是這條流程列唯一要回答的問題。 */
.step.active .dot   { background: var(--db-accent); }
.step.active .label { color: var(--db-accent); font-weight: 500; }

/* 還沒走到的步驟淡出，暗示不能點 */
.step:not(.reachable) { opacity: 0.55; }

@media (max-width: 1100px) {
  .dot   { width: 34px; height: 34px; font-size: 1rem; }
  .label { font-size: 1rem; }
  .step-bar { padding: 0.4rem 0.75rem 0.9rem; }
}
@media (max-width: 640px) {
  /* 手機上標籤只留進行中那一個，不然一行塞不下六步 */
  .step:not(.active) .label { display: none; }
}
</style>
