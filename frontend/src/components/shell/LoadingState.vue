<script setup>

import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

defineProps({
  title: { type: String, default: 'AI 生成中' },
  sub:   { type: String, default: '' },
  image: { type: String, default: '' },   // 有給就顯示這張圖（例如正在辨識的平面圖），取代裝飾插畫
})

const SLOW_AFTER = 40
const sec = ref(0)
let timer
onMounted(() => { timer = setInterval(() => { sec.value++ }, 1000) })
onBeforeUnmount(() => clearInterval(timer))

const elapsed = computed(() => {
  const m = Math.floor(sec.value / 60)
  return m ? `${m} 分 ${sec.value % 60} 秒` : `${sec.value} 秒`
})
const slow = computed(() => sec.value >= SLOW_AFTER)
</script>

<template>
  <div class="loading-state" role="status" aria-live="polite" aria-atomic="false" aria-busy="true">
    <div v-if="image" class="scan">
      <img :src="image" alt="正在辨識的平面圖" />
      <span class="scan-line" aria-hidden="true"></span>
    </div>
    <svg v-else class="scene" viewBox="0 12 360 188" aria-hidden="true" focusable="false">
      <!-- 遠景：山與雲 -->
      <path class="hill" d="M0 140V122Q38 96 84 118T180 108T276 120T360 98V140Z" />
      <g class="cloud cl1" transform="translate(52 34)">
        <circle cx="8" cy="7" r="5" /><circle cx="17" cy="5" r="6.5" /><circle cx="26" cy="8" r="4.5" />
        <rect x="3" y="7" width="28" height="6" rx="3" />
      </g>
      <g class="cloud cl2" transform="translate(226 20) scale(0.75)">
        <circle cx="8" cy="7" r="5" /><circle cx="17" cy="5" r="6.5" /><circle cx="26" cy="8" r="4.5" />
        <rect x="3" y="7" width="28" height="6" rx="3" />
      </g>

      <!-- 水面：波紋與橋下的反光 -->
      <path class="water w1" d="M92 186q6-4 12 0t12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0" />
      <path class="water w2" d="M98 194q6-4 12 0t12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0 12 0" />
      <path class="glint" d="M150 176h20M178 179h12M196 175h8" />

      <!-- 兩岸 -->
      <path class="bank" d="M0 140H84V200H0Z" />
      <path class="bank" d="M276 140H360V200H276Z" />
      <path class="line thin edge" d="M84 145V200M276 145V200" />
      <path class="line" d="M0 140H84M276 140H360" />
      <path class="line hair tuft" d="M8 140l-1.5-4M10.5 140l.5-5M13 140l2-3.5M352 140l-1.5-4M354.5 140l.5-5" />

      <!-- 橋：欄杆、拱、立柱、橋面 -->
      <path class="rail" d="M84 131H276M84 140V131M108 140V131M132 140V131M156 140V131M180 140V131M204 140V131M228 140V131M252 140V131M276 140V131" />
      <path class="line arch" pathLength="1" d="M84 176Q180 118 276 176" />
      <path class="line thin posts" d="M104 145V165.2M124 145V156.9M144 145V151.1M164 145V147.8M196 145V147.8M216 145V151.1M236 145V156.9M256 145V165.2" />
      <rect class="ink deck" x="78" y="140" width="204" height="5" rx="2" />

      <!-- 左岸：畫架上的平面圖、一疊建材 -->
      <path class="line thin" d="M13 124L9 140M31 124L35 140M22 124V140" />
      <g transform="rotate(-5 22 112)">
        <rect class="ink paper" x="8" y="100" width="28" height="24" rx="2" />
        <path class="line hair" d="M12.5 105H31.5V119.5H12.5ZM12.5 112H21M21 112V119.5M26 105V109" />
      </g>
      <rect class="ink block" x="40" y="131" width="12" height="9" rx="1.5" />
      <rect class="ink paper" x="42" y="123" width="10" height="8" rx="1.5" />

      <!-- 右岸：房子的預定輪廓（虛線）＋ 依序蓋上去的三個部分 -->
      <path class="ghost" d="M296 140V113.5H289L318 90L347 113.5H340V140" />
      <g class="part p3"><rect class="ink block" x="331" y="93" width="7" height="15" /></g>
      <g class="part p1">
        <rect class="ink paper" x="296" y="112" width="44" height="28" />
        <path class="line hair base" d="M296 136H340" />
      </g>
      <g class="part p2">
        <path class="ink block" d="M288 114L318 90L348 114Z" />
        <path class="line hair shingle" d="M306 105q3 2.5 6 0M318 105q3 2.5 6 0M312 99q3 2.5 6 0" />
      </g>
      <g class="part p3">
        <path class="ink door" d="M312 140V127a6 6 0 0 1 12 0V140Z" />
        <circle class="dot" cx="321.2" cy="132.5" r="0.9" />
        <rect class="ink pane" x="300.5" y="119" width="8" height="8" rx="1" />
        <path class="line hair" d="M304.5 119V127M300.5 123H308.5" />
        <rect class="ink pane" x="328" y="119" width="8" height="8" rx="1" />
        <path class="line hair" d="M332 119V127M328 123H336" />
      </g>
      <circle class="ink bush" cx="349.5" cy="135" r="5" /><circle class="ink bush" cx="355" cy="137" r="3.5" />
      <!-- 建材落地揚起的小灰塵（每趟一次） -->
      <circle class="dust du1" cx="293" cy="138" r="2.6" /><circle class="dust du2" cx="343" cy="138" r="2.6" />
      <!-- 完工：煙囪飄出愛心、屋頂旁閃兩下 -->
      <g transform="translate(334.5 88)"><path class="puff" d="M0 3C-5-1-2.5-5 0-2 2.5-5 5-1 0 3Z" /></g>
      <g transform="translate(283 98)"><path class="spark" d="M0-5C.6-1.2 1.2-.6 5 0 1.2.6.6 1.2 0 5-.6 1.2-1.2.6-5 0-1.2-.6-.6-1.2 0-5Z" /></g>
      <g transform="translate(351 104) scale(0.7)"><path class="spark sp2" d="M0-5C.6-1.2 1.2-.6 5 0 1.2.6.6 1.2 0 5-.6 1.2-1.2.6-5 0-1.2-.6-.6-1.2 0-5Z" /></g>

      <!-- 倉鼠（面向右；回程整隻翻面） -->
      <g class="walker">
        <ellipse class="shade" cx="60" cy="141.2" rx="12" ry="1.6" />
        <g class="facing"><g class="waddle">
          <circle class="ink fur" cx="45.8" cy="131" r="2" />
          <circle class="ink fur" cx="55" cy="113.5" r="3.8" />
          <circle class="ear-in" cx="55" cy="113.5" r="1.8" />
          <ellipse class="ink foot fa" cx="53" cy="139.2" rx="3.8" ry="1.8" />
          <ellipse class="ink foot fb" cx="65.5" cy="139.2" rx="3.8" ry="1.8" />
          <path class="ink fur" d="M46 129C46 118 52 110.5 61.5 110.5C70 110.5 75.5 116.5 75.5 124.5C75.5 133.5 69 139 60 139C51.5 139 46 135.5 46 129Z" />
          <path class="patch" d="M47.5 126C48 119.5 51.5 114.5 57 112.5C58 119 54.5 124.5 47.5 126Z" />
          <ellipse class="belly" cx="62" cy="133" rx="7" ry="4" />
          <ellipse class="cheek" cx="68.5" cy="128" rx="3.2" ry="2.2" />
          <g class="eye"><circle class="dot" cx="67.5" cy="121" r="1.7" /><circle class="shine" cx="68.1" cy="120.4" r="0.550" /></g>
          <circle class="nose" cx="75.2" cy="125.5" r="1.2" />
          <path class="line hair" d="M73.5 128l4.5.8M73 129.5l4 2.5" />
          <!-- 工地帽 -->
          <path class="ink hat" d="M57 113.5C57 104.5 71.5 104.5 71.5 113.5Z" />
          <path class="line hair" d="M60.5 109.5q3.5-2.5 7.5 0" />
          <path class="line" d="M54.8 113.5H75" />
          <!-- 手上的建材：每趟不同（牆、屋頂、門） -->
          <rect class="ink paper carry c1" x="77" y="122" width="11" height="10" rx="1.5" />
          <path class="ink block carry c2" d="M76 132.5L82.5 122L89 132.5Z" />
          <path class="ink door carry c3" d="M78 133V126.5a4.5 4.5 0 0 1 9 0V133Z" />
          <ellipse class="ink fur" cx="73" cy="131.5" rx="2.8" ry="2" />
        </g></g>
      </g>
    </svg>

    <p class="title">
      <span>{{ title }}</span>
      <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>
    </p>
    <p v-if="sub" class="sub">{{ sub }}</p>
    <p class="elapsed" aria-hidden="true">已等待 {{ elapsed }}</p>
    <p v-if="slow" class="slow">
      比平常久一些：雲端運算閒置一陣子後，第一次生成要先暖機，可能再等幾分鐘。請先不要關閉頁面，完成後會自動顯示。
    </p>

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
  padding: 2.5rem 1.5rem;
  text-align: center;
}

.scene {
  width: min(440px, 88vw);
  height: auto;
  margin-bottom: 0.75rem;
  overflow: visible;
}

.scan {
  position: relative;
  max-width: 100%;
  margin-bottom: 1rem;
  border-radius: 8px;
  overflow: hidden;
  background: var(--db-chip-soft);
}
.scan img { display: block; max-width: 100%; max-height: 440px; object-fit: contain; }
/* 一條淡色光帶上下掃過，表示還在辨識中 */
.scan-line {
  position: absolute; left: 0; right: 0; top: 0;
  height: 18%;
  background: linear-gradient(to bottom, transparent, var(--db-accent-soft), transparent);
  opacity: 0.7;
  animation: scan 2.4s ease-in-out infinite alternate;
}
@keyframes scan { to { transform: translateY(455%); } }

/* ── 線稿共用：只用品牌的灰褐色階 ── */
.ink  { stroke: var(--db-accent-ink); stroke-width: 1.4; stroke-linejoin: round; }
.line { fill: none; stroke: var(--db-accent-ink); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.line.thin { stroke-width: 1.1; }
.line.hair { stroke-width: 0.8; }
.paper { fill: var(--db-card); }
.block { fill: var(--db-accent); }
.door  { fill: var(--db-accent-deep); }
.deck  { fill: var(--db-card); }
.bank  { fill: var(--db-paper); }
.hill  { fill: var(--db-chip-soft); }
.cloud { fill: var(--db-paper); }
.bush  { fill: var(--db-accent-soft); }
.fur   { fill: var(--db-chip-soft); }
.belly { fill: var(--db-card); }
.foot  { fill: var(--db-accent-soft); }
.hat   { fill: var(--db-accent); }
.patch { fill: var(--db-accent); opacity: 0.8; }
.ear-in, .cheek { fill: var(--db-accent-deep); opacity: 0.45; }
.dot   { fill: var(--db-text); }
.nose  { fill: var(--db-accent-ink); }
.shine { fill: #fff; }
.shade { fill: var(--db-accent-ink); opacity: 0.14; }
.edge, .tuft, .shingle, .base { opacity: 0.6; }
.ghost { fill: none; stroke: var(--db-accent); stroke-width: 1.2; stroke-dasharray: 3 3; stroke-linejoin: round; }
.rail  { fill: none; stroke: var(--db-accent-deep); stroke-width: 1; stroke-linecap: round; animation: fade 0.6s ease-out 1s both; }

.cloud { animation: drift 16s ease-in-out infinite alternate; }
.cl2 { animation-duration: 22s; animation-direction: alternate-reverse; }
@keyframes drift { from { translate: -8px 0; } to { translate: 10px 0; } }

.water {
  fill: none;
  stroke: var(--db-accent);
  stroke-width: 1.2;
  stroke-linecap: round;
  stroke-dasharray: 14 10;
  animation: flow 3s linear infinite;
}
.w2 { animation-duration: 4.2s; animation-direction: reverse; opacity: 0.7; }
@keyframes flow { to { stroke-dashoffset: -48; } }
.glint {
  fill: none; stroke: var(--db-accent-soft); stroke-width: 1.4; stroke-linecap: round;
  animation: glint 3.6s ease-in-out infinite;
}
@keyframes glint { 0%, 100% { opacity: 0.25; } 50% { opacity: 1; } }

/* 橋拱進場時一筆畫出來 */
.arch { stroke-width: 2.2; stroke-dasharray: 1; animation: draw 1.2s ease-out both; }
.posts { animation: fade 0.6s ease-out 0.9s both; }
@keyframes draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes fade { from { opacity: 0; } }

/* 一趟 4 秒：0–40% 過橋、放下建材時小跳一下、轉身、54–90% 走回來。三趟（12 秒）蓋完一間再重來 */
.walker { transform: translateX(6px); animation: walk 4s cubic-bezier(0.45, 0.05, 0.55, 0.95) infinite; }
@keyframes walk {
  0%        { transform: translate(6px, 0); }
  40%       { transform: translate(203px, 0); }
  43%       { transform: translate(203px, -3.5px); }
  46%, 54%  { transform: translate(203px, 0); }
  90%, 100% { transform: translate(6px, 0); }
}
.facing { transform-origin: 60px 126px; animation: turn 4s linear infinite; }
@keyframes turn {
  0%, 48%   { transform: scaleX(1); }
  52%, 93%  { transform: scaleX(-1); }
  97%, 100% { transform: scaleX(1); }
}
.waddle { transform-origin: 60px 140px; animation: waddle 0.34s ease-in-out infinite alternate; }
@keyframes waddle { from { transform: rotate(-2.5deg); } to { transform: translateY(-1.4px) rotate(2.5deg); } }
.foot { animation: step 0.34s ease-in-out infinite alternate; }
.fb { animation-direction: alternate-reverse; }
@keyframes step { from { transform: translate(-1px, 0); } to { transform: translate(1.2px, -1.8px); } }
.shade { transform-box: fill-box; transform-origin: center; animation: shade 0.34s ease-in-out infinite alternate; }
@keyframes shade { to { transform: scaleX(0.88); } }
.eye { transform-box: fill-box; transform-origin: center; animation: blink 3.4s ease-in-out infinite; }
@keyframes blink { 0%, 92%, 100% { transform: scaleY(1); } 96% { transform: scaleY(0.1); } }

.carry { opacity: 0; animation: carry 12s linear infinite backwards; }
.c2 { animation-delay: 4s; }
.c3 { animation-delay: 8s; }
@keyframes carry {
  0%          { opacity: 0; }
  1.5%, 13.3% { opacity: 1; }
  13.8%, 100% { opacity: 0; }
}

/* 房子的三個部分：倉鼠每趟抵達（13.3% / 46.7% / 80%）時從上面落下、壓一下再彈回 */
.part { transform-box: fill-box; transform-origin: center bottom; animation: 12s ease-out infinite; }
.p1 { animation-name: part1; }
.p2 { animation-name: part2; }
.p3 { animation-name: part3; }
@keyframes part1 {
  0%, 13.3% { opacity: 0; transform: translateY(-12px) scale(0.9); }
  15.2%     { opacity: 1; transform: scale(1.07, 0.9); }
  16.6%     { opacity: 1; transform: translateY(-2px) scale(0.98, 1.03); }
  18%, 96%  { opacity: 1; transform: none; }
  100%      { opacity: 0; transform: none; }
}
@keyframes part2 {
  0%, 46.7% { opacity: 0; transform: translateY(-12px) scale(0.9); }
  48.6%     { opacity: 1; transform: scale(1.07, 0.9); }
  50%       { opacity: 1; transform: translateY(-2px) scale(0.98, 1.03); }
  51.4%, 96% { opacity: 1; transform: none; }
  100%      { opacity: 0; transform: none; }
}
@keyframes part3 {
  0%, 80%   { opacity: 0; transform: translateY(-12px) scale(0.9); }
  81.9%     { opacity: 1; transform: scale(1.07, 0.9); }
  83.3%     { opacity: 1; transform: translateY(-2px) scale(0.98, 1.03); }
  84.7%, 96% { opacity: 1; transform: none; }
  100%      { opacity: 0; transform: none; }
}
/* 完工後窗戶亮起來 */
.pane { fill: var(--db-card); animation: lit 12s ease-in-out infinite; }
@keyframes lit { 0%, 85% { fill: var(--db-card); } 89%, 100% { fill: var(--db-accent-soft); } }

.dust { fill: var(--db-accent-soft); opacity: 0; transform-box: fill-box; transform-origin: center; animation: dust 4s ease-out infinite; }
.du2 { --dx: 5px; }
@keyframes dust {
  0%, 41% { opacity: 0; transform: translate(0, 0) scale(0.4); }
  44%     { opacity: 0.9; transform: translate(calc(var(--dx, -5px) * 0.5), -1px) scale(1); }
  52%, 100% { opacity: 0; transform: translate(var(--dx, -5px), -4px) scale(1.5); }
}

.puff { fill: var(--db-accent-deep); opacity: 0; animation: puff 12s ease-out infinite; }
@keyframes puff {
  0%, 85% { opacity: 0; transform: translateY(0) scale(0.4); }
  88.5%   { opacity: 1; transform: translateY(-6px) scale(1); }
  96%     { opacity: 0; transform: translate(3px, -20px) scale(1.1); }
  100%    { opacity: 0; }
}
.spark { fill: var(--db-accent-deep); opacity: 0; animation: spark 12s ease-in-out infinite; }
.sp2 { animation-delay: 0.35s; }
@keyframes spark {
  0%, 84%   { opacity: 0; transform: scale(0.2) rotate(0deg); }
  88%       { opacity: 1; transform: scale(1) rotate(45deg); }
  93%, 100% { opacity: 0; transform: scale(0.2) rotate(90deg); }
}

.title {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 0.45rem;
  margin: 0;
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.4rem;
  color: var(--db-text);
}
.dots { display: inline-flex; gap: 4px; }
.dots i {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--db-accent-deep);
  animation: dot 1.2s ease-in-out infinite;
}
.dots i:nth-child(2) { animation-delay: 0.15s; }
.dots i:nth-child(3) { animation-delay: 0.3s; }
@keyframes dot { 0%, 60%, 100% { transform: none; } 30% { transform: translateY(-5px); } }

.sub {
  margin: 0;
  color: var(--db-text-soft);
  font-size: 0.95rem;
}
.elapsed {
  margin: 0.35rem 0 0;
  color: var(--db-text-soft);   /* 不用 placeholder 色：白底對比度不足 */
  font-family: var(--db-font-num);
  font-size: 0.82rem;
  letter-spacing: 0.04em;
  font-variant-numeric: tabular-nums;
}
.slow {
  max-width: 28rem;
  margin: 0.6rem 0 0;
  padding: 0.6rem 0.9rem;
  border-radius: var(--db-radius-chip);
  background: var(--db-paper);
  color: var(--db-text-soft);
  font-size: 0.86rem;
  line-height: 1.7;
}

/* 減少動態：倉鼠站在橋頭、房子已蓋好，不跑動畫 */
@media (prefers-reduced-motion: reduce) {
  .scan-line, .puff, .spark, .dust { display: none; }
  .water, .glint, .cloud, .arch, .posts, .rail, .walker, .facing, .waddle, .foot, .shade, .eye,
  .carry, .part, .pane, .dots i { animation: none; }
  .arch { stroke-dashoffset: 0; }
}
</style>
