<script setup>
/** DEMO 範例 prompt：點一顆就填進描述框並觸發風格推薦（見 config/demoPrompts.js） */
import { useDesignFlow } from '@/composables/useDesignFlow'
import { DEMO_MODE } from '@/config/demo'
import { DEMO_PROMPTS } from '@/config/demoPrompts'

const { extraPrompt, scheduleSearch } = useDesignFlow()

// 填入描述後觸發智慧風格推薦，跟使用者自己打字一樣；風格由使用者在推薦卡片裡挑
function pick(p) {
  extraPrompt.value = p.text
  scheduleSearch()
}
</script>

<template>
  <div v-if="DEMO_MODE" class="demo-chips">
    <span>範例：</span>
    <button v-for="p in DEMO_PROMPTS" :key="p.id" type="button" class="demo-chip" @click="pick(p)">{{ p.text }}</button>
  </div>
</template>

<style scoped>
.demo-chips { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-top: 0.6rem; font-size: 0.85rem; color: var(--db-text-soft); }
.demo-chip {
  padding: 0.3rem 0.8rem;
  border: 1px solid #cfcfcf;
  border-radius: 999px;
  background: var(--db-chip-soft);
  cursor: pointer;
}
.demo-chip:hover { border-color: var(--db-accent); }
</style>
