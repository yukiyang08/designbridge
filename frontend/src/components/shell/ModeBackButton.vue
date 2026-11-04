<script setup>
/** 回入口頁重選模式：只放在各流程第一步，底部操作列的左邊（＝第一步的「上一步」）。 */
import { useRouter } from 'vue-router'
import { useDesignFlow } from '@/composables/useDesignFlow'

const router = useRouter()
const { resetFlow, confirmDiscard, loading } = useDesignFlow()

function back() {
  if (!confirmDiscard()) return
  resetFlow()
  router.push('/start')
}
</script>

<template>
  <button type="button" class="mode-back-btn" :disabled="loading" @click="back">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <polyline points="15 18 9 12 15 6" />
    </svg>
    重新選擇模式
  </button>
</template>

<style scoped>
.mode-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 1.1rem;
  min-height: 44px;
  border: 2px solid #dcdcdc;
  border-radius: var(--db-radius-pill);
  background: #fff;
  color: var(--db-text);
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1rem;
  cursor: pointer;
  transition: border-color 0.16s, background 0.16s, transform 0.12s;
}
.mode-back-btn:hover:not(:disabled) {
  border-color: var(--db-accent);
  background: #f7f6f3;
  transform: translateX(-2px);
}
.mode-back-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.mode-back-btn svg { flex-shrink: 0; }

@media (prefers-reduced-motion: reduce) {
  .mode-back-btn:hover:not(:disabled) { transform: none; }
}
</style>
