<script setup>
import { ref } from 'vue'

/**
 * 設計稿的白卡容不下舊版側欄的全部欄位，但那些欄位（長寬比、自訂長寬、家庭結構、
 * 風水、風格參考圖、styleMethod…）都是實際會影響生成結果的參數，不能刪。
 * 統一收進這個預設摺疊的區塊：第一眼維持設計稿的乾淨，進階使用者展開就拿得到全部。
 */
defineProps({
  title: { type: String, default: '進階設定' },
  hint:  { type: String, default: '' },
})

const open = ref(false)
</script>

<template>
  <div class="advanced">
    <!-- 箭頭放在文字「前面」而且按鈕不滿版：滿版方框 + 最右邊的 chevron
         看起來就是一個 <select>，實測有人以為要下拉選東西。 -->
    <button type="button" class="toggle" :aria-expanded="open" @click="open = !open">
      <svg class="arrow" :class="{ open }" width="14" height="14" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"
        stroke-linejoin="round" aria-hidden="true">
        <polyline points="9 6 15 12 9 18" />
      </svg>
      <span class="toggle-text">{{ title }}</span>
      <span v-if="hint" class="toggle-hint">{{ open ? '' : hint }}</span>
    </button>
    <div v-show="open" class="body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.advanced {
  border-top: 1px solid #ececec;
  margin-top: 0.5rem;
}

.toggle {
  display: inline-flex;       /* 不滿版，才不會被讀成一個輸入框 */
  align-items: center;
  gap: 0.5rem;
  margin: 0.85rem 0;
  padding: 0.4rem 0.7rem;
  border: none;
  border-radius: 8px;
  background: none;
  color: var(--db-text-soft);
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.05rem;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}
.toggle:hover { color: var(--db-text); background: var(--db-chip-soft); }
/* 自訂 focus 樣式，蓋掉瀏覽器預設的藍框——藍框把它變得更像 select */
.toggle:focus-visible {
  outline: 2px solid var(--db-accent);
  outline-offset: 2px;
  color: var(--db-text);
}

.toggle-hint {
  font-family: var(--db-font-body);
  font-style: normal;
  font-size: 0.82rem;
  color: var(--db-placeholder);
}

/* 收合時朝右、展開時朝下 —— 標準的 disclosure triangle */
.arrow {
  flex-shrink: 0;
  color: var(--db-accent);
  transition: transform 0.2s;
}
.arrow.open { transform: rotate(90deg); }

/* 展開的內容縮排並加左側色條，讓它明顯屬於上面那個開關 */
.body {
  display: grid;
  gap: 1.25rem;
  margin: 0 0 1.25rem 0.7rem;
  padding: 0.25rem 0 0.5rem 1.25rem;
  border-left: 3px solid var(--db-accent-soft);
}
</style>
