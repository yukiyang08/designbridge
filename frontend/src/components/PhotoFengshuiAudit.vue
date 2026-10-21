<script setup>
/**
 * 照片風水＋動線健檢：上傳現況照 → AI 推估俯視平面 → 打分、列出違規、在照片上框出來。
 *
 * 單張照片看不到鏡頭背後那面牆，門常常在那裡，所以門的位置一定讓使用者確認／改；
 * 改門只重算報告（/api/fengshui/audit），不重打 Gemini。
 */
import { computed, watch } from 'vue'
import FengshuiReport from '@/components/FengshuiReport.vue'
import FengshuiMiniPlan from '@/components/FengshuiMiniPlan.vue'
import { useDesignFlow } from '@/composables/useDesignFlow'

const {
  spacePhoto, photoAudit, photoAuditLoading, photoAuditError,
  runPhotoAudit, movePhotoDoor, adoptPhotoAudit, fengshuiEnabled, fengshuiExcluded,
} = useDesignFlow()

// 換照片後舊的健檢結果就不是這張的了
watch(() => spacePhoto.preview, () => { photoAudit.value = null; photoAuditError.value = '' })

const plan = computed(() => photoAudit.value?.plan || null)
const report = computed(() => photoAudit.value?.report || null)
const failedRules = computed(() => (report.value?.fengshui?.rules || []).filter(r => r.status === 'fail'))
const offenders = computed(() => [
  ...failedRules.value.flatMap(r => r.offenders),
  ...(report.value?.circulation?.issues || []).flatMap(i => i.offenders),
])
const boxes = computed(() => {
  if (!plan.value) return []
  const bad = new Set(offenders.value)
  const items = plan.value.placements
    .filter(p => p.image_box && bad.has(p.id))
    .map(p => ({ key: p.id, box: p.image_box }))
  if (bad.has('door')) {
    for (const [i, d] of plan.value.doors.entries()) if (d.image_box) items.push({ key: `door${i}`, box: d.image_box })
  }
  return items
})
const boxStyle = ([x0, y0, x1, y1]) => ({
  left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%`,
})

const door = computed(() => plan.value?.doors?.[0] || null)
const WALL_CHOICES = [
  { value: 'far', label: '照片深處' },
  { value: 'left', label: '左側牆' },
  { value: 'right', label: '右側牆' },
  { value: 'near', label: '拍照這一側' },
]
function setDoorWall(wall) { movePhotoDoor(0, wall, door.value?.pos ?? 0.5) }
let doorTimer = null
function setDoorPos(e) {
  const frac = Number(e.target.value)
  clearTimeout(doorTimer)
  doorTimer = setTimeout(() => movePhotoDoor(0, door.value.wall, frac), 250)
}

const adopted = computed(() => fengshuiEnabled.value
  && failedRules.value.every(r => !fengshuiExcluded.value.includes(r.trigger)))
</script>

<template>
  <section class="photo-audit">
    <header class="pa-head">
      <h2 class="db-col-title pa-title">風水＋動線健檢</h2>
      <p class="pa-hint">AI 會辨識照片裡的家具與門窗，幫你檢查現在的擺法有沒有風水禁忌、走道夠不夠寬。</p>
    </header>

    <div v-if="!photoAudit" class="pa-start">
      <button
        type="button" class="db-btn db-btn--ghost"
        :disabled="!spacePhoto.file || photoAuditLoading" @click="runPhotoAudit"
      >{{ photoAuditLoading ? '分析中…約 10–20 秒' : '幫這張照片做健檢' }}</button>
      <p v-if="photoAuditError" class="pa-error" role="alert">{{ photoAuditError }}</p>
    </div>

    <template v-else>
      <div class="pa-visual">
        <div class="pa-photo">
          <img :src="spacePhoto.preview" alt="空間照片" />
          <span v-for="b in boxes" :key="b.key" class="pa-box" :style="boxStyle(b.box)" />
        </div>
        <FengshuiMiniPlan :plan="plan" :offenders="offenders" photo class="pa-plan" />
      </div>

      <div v-if="door" class="pa-door">
        <p class="pa-door-q">
          {{ door.assumed ? '照片裡看不到門，先假設在拍照這一側。門實際在哪裡？' : '門的位置對嗎？不對的話可以改：' }}
        </p>
        <div class="pa-door-walls" role="group" aria-label="門所在的牆">
          <button
            v-for="w in WALL_CHOICES" :key="w.value" type="button"
            class="db-chip" :class="{ 'is-active': !door.assumed && door.wall === w.value }"
            @click="setDoorWall(w.value)"
          >{{ w.label }}</button>
        </div>
        <label class="pa-door-pos">
          <span>沿牆位置</span>
          <input type="range" min="0.05" max="0.95" step="0.05" :value="door.pos ?? 0.5" @input="setDoorPos" />
        </label>
      </div>

      <FengshuiReport :report="report" :placements="plan.placements" enabled />

      <p v-if="plan.confidence === 'low'" class="pa-note">這張照片的辨識信心偏低，結果僅供參考；拍得越完整越準。</p>
      <p v-if="photoAuditError" class="pa-error" role="alert">{{ photoAuditError }}</p>

      <div class="pa-actions">
        <p v-if="adopted" class="pa-adopted">✓ 下一步生成效果圖時，會依風水重新擺放家具</p>
        <button v-else-if="failedRules.length" type="button" class="db-btn db-btn--sm" @click="adoptPhotoAudit">
          生成時依風水重新擺放
        </button>
        <button type="button" class="pa-link" :disabled="photoAuditLoading" @click="runPhotoAudit">重新分析</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.photo-audit {
  margin-top: 1.5rem;
  padding: 1.5rem clamp(1rem, 3vw, 2rem) 1.25rem;
  border-top: 1px solid #e6e2d8;
}
.pa-head { text-align: center; }
.pa-title { margin-bottom: 0.4rem; }
.pa-hint { margin: 0 auto; max-width: 46ch; color: var(--db-text-soft); font-size: 0.88rem; line-height: 1.6; }

.pa-start { display: flex; flex-direction: column; align-items: center; gap: 0.6rem; margin-top: 1rem; }
.pa-error { margin: 0; color: var(--db-danger); font-size: 0.85rem; }

.pa-visual {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: 1rem;
  align-items: start;
  margin-top: 1.1rem;
}
.pa-photo { position: relative; display: inline-block; justify-self: center; line-height: 0; }
.pa-photo img { display: block; max-width: 100%; max-height: 320px; border-radius: 8px; }
.pa-box {
  position: absolute;
  border: 2px solid var(--db-danger);
  border-radius: 4px;
  background: rgba(180, 68, 58, 0.12);
  pointer-events: none;
}

.pa-door { margin-top: 1rem; }
.pa-door-q { margin: 0 0 0.5rem; font-size: 0.88rem; }
.pa-door-walls { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.pa-door-walls .db-chip { font-size: 0.85rem; padding: 0.35rem 0.85rem; }
.pa-door-pos { display: flex; align-items: center; gap: 0.6rem; margin-top: 0.6rem; font-size: 0.82rem; color: var(--db-text-soft); }
.pa-door-pos input { flex: 1; max-width: 260px; accent-color: var(--db-ink); }

.pa-note { margin: 0.8rem 0 0; color: var(--db-text-soft); font-size: 0.8rem; }
.pa-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem 1.25rem; margin-top: 1rem; }
.pa-adopted { margin: 0; color: var(--db-ok); font-size: 0.9rem; }
.pa-link {
  border: none; background: none; padding: 0;
  color: var(--db-text-soft); font: inherit; font-size: 0.85rem;
  text-decoration: underline; text-underline-offset: 3px; cursor: pointer;
}

@media (max-width: 700px) {
  .pa-visual { grid-template-columns: 1fr; }
}
</style>
