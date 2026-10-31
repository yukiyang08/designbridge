<script setup>
/**
 * 照片入口的偵測／佈局面板，放在結果頁上，跟渲染圖、換風格、局部修改同一頁。
 * 左：原照片＋偵測框；右：俯視佈局（拖曳移動）。改完按「依新佈局重新生圖」。
 */
import { computed } from 'vue'
import LayoutEditor from '@/components/LayoutEditor.vue'
import { furnitureLabel } from '@/config/furniture'
import { mediaUrl } from '@/config/api'
import { useDesignFlow } from '@/composables/useDesignFlow'

const {
  spacePhoto, spacePhotoPath, photoDetection, photoLayoutLoading, photoLayoutError,
  editPlacements, roomW, roomD, roomTypeForPlan,
  autoRelayoutPhoto, resetPhotoLayout, detectPhotoLayout,
  result, loading, swappingStyle, submit3D,
} = useDesignFlow()

const photoUrl = computed(() => spacePhoto.preview || mediaUrl(spacePhotoPath.value))

// 跟偵測結果比，位置或大小變了就標「已移動」；不見了的標「已移除」
const moved = (a, b) => ['x', 'y', 'w', 'h'].some(k => Math.abs((a[k] ?? 0) - (b[k] ?? 0)) > 0.01)
const boxes = computed(() => (photoDetection.value?.furniture_placements || [])
  .filter(p => Array.isArray(p.image_box))
  .map(p => {
    const now = editPlacements.value.find(e => e.id === p.id)
    const base = photoDetection.value.baseline.find(e => e.id === p.id) || p
    const [x0, y0, x1, y1] = p.image_box
    return {
      id: p.id,
      label: furnitureLabel(p.type),
      state: !now ? 'removed' : moved(now, base) ? 'moved' : 'same',
      style: { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` },
    }
  }))
const changed = computed(() => {
  const det = photoDetection.value?.baseline || []
  return editPlacements.value.length !== det.length
    || editPlacements.value.some(e => { const d = det.find(p => p.id === e.id); return !d || moved(e, d) })
})
function onPlacements(next) { editPlacements.value = next }
const busy = computed(() => photoLayoutLoading.value || loading.value || swappingStyle.value)
</script>

<template>
  <section class="photo-layout">
    <header class="pl-head">
      <h3 class="pl-title">偵測到的家具與佈局</h3>
      <span v-if="photoDetection" class="pl-count">{{ editPlacements.length }} 件</span>
      <div class="pl-actions">
        <button type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="busy || !photoDetection" @click="autoRelayoutPhoto">
          AI 自動重排
        </button>
        <button type="button" class="db-btn db-btn--ghost db-btn--sm" :disabled="busy || !changed" @click="resetPhotoLayout">
          還原偵測結果
        </button>
        <button v-if="result" type="button" class="db-btn db-btn--sm" :disabled="busy || !editPlacements.length" @click="submit3D">
          依新佈局重新生圖
        </button>
      </div>
    </header>

    <p v-if="photoLayoutError" class="db-error">
      {{ photoLayoutError }}
      <button v-if="!photoDetection" type="button" class="pl-retry" :disabled="busy" @click="detectPhotoLayout">重試</button>
    </p>
    <p v-else-if="photoLayoutLoading" class="pl-hint" role="status">AI 處理中…</p>

    <div v-if="photoDetection" class="pl-grid">
      <figure class="pl-photo">
        <div class="pl-photo-wrap">
          <img :src="photoUrl" alt="上傳的空間照片" />
          <span v-for="b in boxes" :key="b.id" class="pl-box" :class="`is-${b.state}`" :style="b.style">
            <span class="pl-tag">{{ b.label }}<template v-if="b.state === 'moved'">・已移動</template><template v-else-if="b.state === 'removed'">・已移除</template></span>
          </span>
        </div>
        <figcaption class="pl-hint">照片上的框是 AI 偵測到的家具；右邊的俯視圖可以拖曳、旋轉、刪除或新增。</figcaption>
      </figure>
      <div class="pl-editor">
        <LayoutEditor
          :placements="editPlacements"
          v-model:room-w="roomW"
          v-model:room-d="roomD"
          :room-type="roomTypeForPlan"
          @update:placements="onPlacements"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.photo-layout {
  margin-bottom: 1.75rem;
  padding: 1.1rem 1.1rem 1.25rem;
  border: 1px solid #ececec;
  border-radius: var(--db-radius-chip);
  background: #fff;
}
.pl-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem 0.9rem; margin-bottom: 0.9rem; }
.pl-title {
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 1.25rem;
  color: var(--db-text);
}
.pl-count { color: var(--db-text-soft); font-size: 0.9rem; }
.pl-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-left: auto; }
.pl-hint { margin: 0.5rem 0 0; font-size: 0.8rem; color: var(--db-text-soft); }
.pl-retry {
  margin-left: 0.5rem; border: none; background: none; color: inherit;
  text-decoration: underline; cursor: pointer;
}
.pl-grid { display: grid; gap: 1.25rem; }
/* 編輯器自帶家具面板，窄於這個寬度時並排會把畫布擠到面板下方 */
@media (min-width: 1400px) {
  .pl-grid { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); align-items: start; }
}
.pl-photo { margin: 0; }
.pl-photo-wrap { position: relative; line-height: 0; }
.pl-photo-wrap img { width: 100%; height: auto; border-radius: 8px; }
.pl-box {
  position: absolute;
  border: 2px solid #3b82f6;
  border-radius: 4px;
  background: rgba(59, 130, 246, 0.08);
  pointer-events: none;
}
.pl-box.is-moved { border-color: #f59e0b; border-style: dashed; background: rgba(245, 158, 11, 0.08); }
.pl-box.is-removed { border-color: #9ca3af; border-style: dashed; background: rgba(156, 163, 175, 0.15); }
.pl-tag {
  position: absolute;
  top: -1px;
  left: -1px;
  padding: 2px 6px;
  border-radius: 4px 0 4px 0;
  background: #3b82f6;
  color: #fff;
  font-size: 0.72rem;
  line-height: 1.4;
  white-space: nowrap;
}
.is-moved .pl-tag { background: #f59e0b; }
.is-removed .pl-tag { background: #9ca3af; }
.pl-editor { min-width: 0; }
</style>
