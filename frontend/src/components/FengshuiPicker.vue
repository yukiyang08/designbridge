<script setup>
/**
 * 風水禁忌選單——主畫面的一個區塊，不是進階設定裡的一排 chip。
 *
 * 會拉出來的理由：這些規則是**硬約束**，勾了之後排版會實際把家具移開位置，
 * 對結果的影響跟房型、家具一個等級；收在摺疊面板裡多數人不會展開，等於做了沒人用。
 *
 * 每張卡片直接寫出「是什麼」跟「會怎麼改」，因為「開門不見灶」「穿堂煞」這種詞
 * 只給四個字的話，看得懂的人不需要它、看不懂的人也不會去勾。
 *
 * 與目前房型無關的規則不藏起來、只收進摺疊區：房型是使用者隨時會改的欄位，
 * 而且自訂房型（「和室」「更衣室」）對不上任何清單，全部藏掉會變成永遠選不到。
 */
import { computed } from 'vue'
import { Icon } from '@iconify/vue'
import { FENGSHUI_OPTIONS } from '@/composables/useDesignFlow'

const props = defineProps({
  /** 目前的房型，用來決定哪些規則排在前面（可不給，不給就全部視為相關）。 */
  roomType: { type: String, default: '' },
  /** 標題下方那句話；不同入口（排家具／上傳照片）可以換句話講。 */
  hint: {
    type: String,
    default: '勾選的項目會變成硬性條件，排版時實際把家具移出禁忌位置。',
  },
})

const rules = defineModel({ type: Array, default: () => [] })

const relevant = computed(() => {
  const hit = FENGSHUI_OPTIONS.filter(o => o.rooms.includes(props.roomType))
  // 自訂房型（「和室」「更衣室」）對不上任何清單。此時全部當成相關，
  // 否則主格子會是空的、所有選項都躲在收合區裡，等於整個區塊消失。
  return hit.length ? hit : FENGSHUI_OPTIONS
})
const others = computed(() => FENGSHUI_OPTIONS.filter(o => !relevant.value.includes(o)))

const selectedCount = computed(
  () => FENGSHUI_OPTIONS.filter(o => rules.value.includes(o.value)).length,
)
const allRelevantOn = computed(
  () => relevant.value.length > 0 && relevant.value.every(o => rules.value.includes(o.value)),
)

function toggle(value) {
  rules.value = rules.value.includes(value)
    ? rules.value.filter(v => v !== value)
    : [...rules.value, value]
}

/** 一鍵套用這個房型的全部規則；已經全開時再按一次就是全關，按鈕才不會按了沒反應。 */
function toggleRelevant() {
  const values = relevant.value.map(o => o.value)
  rules.value = allRelevantOn.value
    ? rules.value.filter(v => !values.includes(v))
    : [...new Set([...rules.value, ...values])]
}

function clearAll() {
  rules.value = []
}
</script>

<template>
  <section class="fengshui">
    <header class="fs-head">
      <h2 class="db-col-title fs-title">風水禁忌</h2>
      <p class="fs-hint">{{ hint }}</p>
    </header>

    <div class="fs-bar">
      <span class="fs-count">
        <template v-if="selectedCount">已選 {{ selectedCount }} 條</template>
        <template v-else>尚未勾選，不勾就不會限制排版</template>
      </span>
      <div class="fs-bar-actions">
        <button v-if="relevant.length" type="button" class="fs-link" @click="toggleRelevant">
          {{ allRelevantOn ? '取消這些' : '全部套用' }}
        </button>
        <button v-if="selectedCount" type="button" class="fs-link" @click="clearAll">
          全部清除
        </button>
      </div>
    </div>

    <div class="fs-grid">
      <button
        v-for="opt in relevant" :key="opt.value"
        type="button"
        class="fs-card"
        :class="{ 'is-active': rules.includes(opt.value) }"
        :aria-pressed="rules.includes(opt.value)"
        @click="toggle(opt.value)"
      >
        <Icon :icon="opt.icon" class="fs-icon" aria-hidden="true" />
        <span class="fs-text">
          <span class="fs-label">{{ opt.label }}</span>
          <span class="fs-desc">{{ opt.desc }}</span>
          <span class="fs-fix">{{ opt.fix }}</span>
        </span>
        <Icon
          :icon="rules.includes(opt.value) ? 'mdi:check-circle' : 'mdi:circle-outline'"
          class="fs-check"
          aria-hidden="true"
        />
      </button>
    </div>

    <details v-if="others.length" class="fs-more">
      <summary class="fs-summary">
        其他空間的規則（{{ others.length }}）
        <span v-if="others.some(o => rules.includes(o.value))" class="fs-more-badge">
          已選 {{ others.filter(o => rules.includes(o.value)).length }}
        </span>
      </summary>
      <div class="fs-grid fs-grid--compact">
        <button
          v-for="opt in others" :key="opt.value"
          type="button"
          class="fs-card fs-card--compact"
          :class="{ 'is-active': rules.includes(opt.value) }"
          :aria-pressed="rules.includes(opt.value)"
          @click="toggle(opt.value)"
        >
          <Icon :icon="opt.icon" class="fs-icon" aria-hidden="true" />
          <span class="fs-text">
            <span class="fs-label">{{ opt.label }}</span>
            <span class="fs-desc">{{ opt.desc }}</span>
          </span>
          <Icon
            :icon="rules.includes(opt.value) ? 'mdi:check-circle' : 'mdi:circle-outline'"
            class="fs-check"
            aria-hidden="true"
          />
        </button>
      </div>
    </details>
  </section>
</template>

<style scoped>
.fengshui {
  margin-top: 1.5rem;
  padding: 1.5rem clamp(1rem, 3vw, 2rem) 1.6rem;
  border-top: 1px solid #e6e2d8;
  /* 勾選狀態原本用全站共用的 --db-accent-soft/-deep（米杏底+卡其邊），跟其他一般
     互動元件同色，勾了之後對比太弱、看起來不像硬性條件。這裡只加深同一組色相、
     邊框改墨色，維持低彩度調性但拉開對比——只有這個元件在用，不升級成全站 token。 */
  --fs-active-bg: #faf8f2;
  --fs-active-border: #2b2822;
}

.fs-head { text-align: center; }
.fs-title { margin-bottom: 0.4rem; }
.fs-hint {
  margin: 0 auto;
  max-width: 46ch;
  color: var(--db-text-soft);
  font-size: 0.88rem;
  line-height: 1.6;
}

.fs-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin: 1.1rem 0 0.8rem;
}
.fs-count { color: var(--db-text-soft); font-size: 0.85rem; }
.fs-bar-actions { display: flex; gap: 0.9rem; }
.fs-link {
  border: none;
  background: none;
  padding: 0;
  color: var(--db-text);
  font-family: var(--db-font-body);
  font-size: 0.85rem;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}
.fs-link:hover { color: var(--db-accent-deep); }

/* auto-fill + minmax：窄畫面自動掉成一欄，不需要另外寫 media query */
.fs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(244px, 1fr));
  gap: 0.7rem;
}

.fs-card {
  display: flex;
  align-items: flex-start;
  gap: 0.7rem;
  padding: 0.85rem 0.9rem;
  border: 2px solid transparent;
  border-radius: var(--db-radius-chip);
  background: var(--db-chip-soft);
  color: var(--db-text);
  text-align: left;
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s, box-shadow 0.16s;
}
.fs-card:hover:not(.is-active) { background: #e4e4e4; }
.fs-card.is-active {
  background: var(--fs-active-bg);
  border-color: var(--fs-active-border);
  box-shadow: var(--db-shadow-soft);
}

.fs-icon { flex: none; width: 22px; height: 22px; margin-top: 2px; color: var(--db-text-soft); }
.fs-card.is-active .fs-icon { color: var(--db-text); }

.fs-text { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; flex: 1; }
.fs-label {
  font-family: var(--db-font-display);
  font-style: normal;
  font-weight: 600;
  font-size: 1.05rem;
  line-height: 1.3;
}
.fs-desc { color: var(--db-text-soft); font-size: 0.8rem; line-height: 1.5; }
/* 「會怎麼改」只在勾起來之後才需要看，平常淡出去不跟說明搶注意力 */
.fs-fix {
  margin-top: 0.15rem;
  color: var(--db-secondary);
  font-size: 0.75rem;
  line-height: 1.45;
  opacity: 0.75;
}
.fs-card.is-active .fs-fix { opacity: 1; color: var(--db-text-soft); }

.fs-check { flex: none; width: 19px; height: 19px; margin-top: 3px; color: var(--db-placeholder); }
.fs-card.is-active .fs-check { color: var(--fs-active-border); }

.fs-more { margin-top: 0.9rem; }
.fs-summary {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0;
  color: var(--db-text-soft);
  font-size: 0.85rem;
  cursor: pointer;
  list-style: revert;
}
.fs-summary:hover { color: var(--db-text); }
.fs-more[open] .fs-summary { margin-bottom: 0.6rem; }
.fs-more-badge {
  padding: 0.1rem 0.5rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent);
  color: var(--db-on-accent);
  font-size: 0.72rem;
}

.fs-card--compact { padding: 0.65rem 0.8rem; }
.fs-card--compact .fs-label { font-size: 0.98rem; }

@media (max-width: 600px) {
  .fengshui { padding-inline: 0.5rem; }
}
</style>
