<script setup>
/**
 * 風水建議開關——主畫面只問「要不要套用」，不要求使用者看懂 14 條規則。
 *
 * 開啟後依房型自動挑規則（relevantFengshuiOptions），細調收在摺疊區、依四個原則分組；
 * 取消勾選的規則記在 fengshuiExcluded，換房型時其餘規則照樣自動帶入。
 */
import { computed } from 'vue'
import { useDesignFlow, FENGSHUI_GROUPS, relevantFengshuiOptions } from '@/composables/useDesignFlow'
import { FENGSHUI_DIAGRAMS } from './fengshuiDiagrams'

const props = defineProps({
  roomType: { type: String, default: '' },
  /** 開關下方那句話；不同入口（排家具／上傳照片）講法不同。 */
  hint: { type: String, default: '開啟後，排版時會自動把家具移出風水禁忌的位置。' },
})

const { fengshuiEnabled, fengshuiExcluded } = useDesignFlow()

const options = computed(() => relevantFengshuiOptions(props.roomType))
const activeCount = computed(() => options.value.filter(o => !fengshuiExcluded.value.includes(o.value)).length)
const groups = computed(() => FENGSHUI_GROUPS
  .map(g => ({ ...g, items: options.value.filter(o => o.group === g.key) }))
  .filter(g => g.items.length))

function toggleRule(value) {
  fengshuiExcluded.value = fengshuiExcluded.value.includes(value)
    ? fengshuiExcluded.value.filter(v => v !== value)
    : [...fengshuiExcluded.value, value]
}
</script>

<template>
  <section class="fengshui">
    <label class="fs-switch">
      <span class="fs-switch-text">
        <span class="fs-title">套用風水建議</span>
        <span class="fs-hint">{{ hint }}</span>
      </span>
      <input v-model="fengshuiEnabled" type="checkbox" role="switch" class="fs-switch-input" />
      <span class="fs-switch-track" aria-hidden="true"><span class="fs-switch-thumb" /></span>
    </label>

    <div v-if="fengshuiEnabled" class="fs-body">
      <p class="fs-summary">
        已依這個空間自動套用 <strong>{{ activeCount }}</strong> 條規則，涵蓋：
      </p>
      <ul class="fs-groups">
        <li v-for="g in groups" :key="g.key" class="fs-group-chip" :title="g.desc">{{ g.label }}</li>
      </ul>

      <details class="fs-more">
        <summary>細調規則</summary>
        <div v-for="g in groups" :key="g.key" class="fs-group">
          <p class="fs-group-title">{{ g.label }}<span>{{ g.desc }}</span></p>
          <label v-for="opt in g.items" :key="opt.value" class="fs-rule">
            <input
              type="checkbox"
              :checked="!fengshuiExcluded.includes(opt.value)"
              @change="toggleRule(opt.value)"
            />
            <span v-if="FENGSHUI_DIAGRAMS[opt.value]" class="fs-diagram" aria-hidden="true" v-html="FENGSHUI_DIAGRAMS[opt.value]" />
            <span class="fs-rule-text">
              <span class="fs-rule-label">{{ opt.label }}</span>
              <span class="fs-rule-desc">{{ opt.desc }}</span>
            </span>
          </label>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.fengshui {
  margin-top: 1.5rem;
  padding: 1.25rem clamp(1rem, 3vw, 2rem);
  border-top: 1px solid #e6e2d8;
}

.fs-switch {
  display: flex;
  align-items: center;
  gap: 1rem;
  cursor: pointer;
}
.fs-switch-text { display: flex; flex-direction: column; gap: 0.2rem; flex: 1; min-width: 0; }
.fs-title {
  font-family: var(--db-font-display);
  font-weight: 600;
  font-size: 1.15rem;
}
.fs-hint { color: var(--db-text-soft); font-size: 0.85rem; line-height: 1.55; }

.fs-switch-input { position: absolute; opacity: 0; pointer-events: none; }
.fs-switch-track {
  flex: none;
  position: relative;
  width: 46px;
  height: 26px;
  border-radius: var(--db-radius-pill);
  background: var(--db-chip);
  transition: background 0.16s;
}
.fs-switch-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.16s;
}
.fs-switch-input:checked + .fs-switch-track { background: var(--db-ink); }
.fs-switch-input:checked + .fs-switch-track .fs-switch-thumb { transform: translateX(20px); }
.fs-switch-input:focus-visible + .fs-switch-track { outline: 2px solid var(--db-accent-ink); outline-offset: 2px; }

.fs-body { margin-top: 1rem; }
.fs-summary { margin: 0 0 0.5rem; font-size: 0.88rem; color: var(--db-text-soft); }
.fs-summary strong { color: var(--db-text); }
.fs-groups { display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0; padding: 0; list-style: none; }
.fs-group-chip {
  padding: 0.3rem 0.8rem;
  border-radius: var(--db-radius-pill);
  background: var(--db-accent-soft);
  font-size: 0.85rem;
}

.fs-more { margin-top: 0.9rem; }
.fs-more summary {
  color: var(--db-text-soft);
  font-size: 0.85rem;
  cursor: pointer;
}
.fs-more summary:hover { color: var(--db-text); }
.fs-group { margin-top: 0.8rem; }
.fs-group-title { margin: 0 0 0.35rem; font-weight: 600; font-size: 0.9rem; }
.fs-group-title span { margin-left: 0.5rem; font-weight: 400; color: var(--db-text-soft); font-size: 0.8rem; }

.fs-rule {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.45rem 0.6rem;
  border-radius: var(--db-radius-chip);
  cursor: pointer;
}
.fs-rule:hover { background: var(--db-chip-soft); }
.fs-rule input { flex: none; width: 16px; height: 16px; accent-color: var(--db-ink); }
.fs-diagram { flex: none; width: 44px; height: 33px; color: var(--db-text-soft); }
.fs-diagram :deep(svg) { display: block; width: 100%; height: 100%; }
.fs-rule-text { display: flex; flex-direction: column; min-width: 0; }
.fs-rule-label { font-size: 0.92rem; }
.fs-rule-desc { color: var(--db-text-soft); font-size: 0.78rem; line-height: 1.45; }

@media (max-width: 600px) {
  .fengshui { padding-inline: 0.5rem; }
  .fs-group-title span { display: block; margin-left: 0; }
}
/* 手機：每條規則縮成一行（只留名稱與勾選），說明文字勾起來才展開 */
@media (max-width: 640px) {
  .fs-grid { grid-template-columns: 1fr; gap: 0.45rem; }
  .fs-card { align-items: center; padding: 0.55rem 0.75rem; }
  .fs-diagram { width: 40px; height: 30px; }
  .fs-desc, .fs-fix { display: none; }
  .fs-card.is-active .fs-desc { display: block; }
  .fs-label { font-size: 0.98rem; }
}
</style>
