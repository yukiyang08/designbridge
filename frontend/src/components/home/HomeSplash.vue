<script setup>
/**
 * 首頁開場：第一次打開網站時播一次品牌動畫。播到一半白底淡出、首頁從後面浮現，
 * 最後 logo 縮小飛進導覽列 logo 的位置接上（兩邊 viewBox 相同，位置大小可以直接對齊）。
 * 同一個分頁工作階段只播一次；點一下或按任意鍵跳過；系統設定減少動態時不播。
 */
import { ref, onMounted, onBeforeUnmount } from 'vue'
import BrandIntro from '@/components/shell/BrandIntro.vue'
import { prefersReducedMotion } from '@/composables/useScrollProgress'

const SEEN_KEY = 'db-intro-seen'
const REVEAL_AT_MS = 1600   // 屋頂合攏、窗亮起之後，白底開始淡出
const HOLD_MS = 250         // 動畫播完停一下再飛
const FLY_MS = 800

function alreadySeen() {
  try { return sessionStorage.getItem(SEEN_KEY) === '1' } catch { return false }
}
function markSeen() {
  try { sessionStorage.setItem(SEEN_KEY, '1') } catch { /* 存不了就每次都播，不影響使用 */ }
}

const show = ref(!alreadySeen() && !prefersReducedMotion())
const revealed = ref(false)
const flying = ref(false)
const logoEl = ref(null)
const flyStyle = ref({})
const timers = []
const later = (fn, ms) => timers.push(setTimeout(fn, ms))

function close() {
  show.value = false
  document.documentElement.classList.remove('db-splash')
  document.documentElement.style.overflow = ''
  window.removeEventListener('keydown', skip)
}

// 把開場的 logo 移到導覽列 logo 的位置；找不到導覽列 logo 就原地淡出
function fly() {
  if (flying.value) return
  flying.value = true
  revealed.value = true
  const target = document.querySelector('.app-nav .brand img')?.getBoundingClientRect()
  const from = logoEl.value?.getBoundingClientRect()
  if (target?.width && from?.width) {
    const k = target.width / from.width
    flyStyle.value = { transform: `translate(${target.left - from.left}px, ${target.top - from.top}px) scale(${k})` }
  } else {
    flyStyle.value = { opacity: 0 }
  }
  later(close, FLY_MS)
}

function skip() {
  timers.forEach(clearTimeout)
  fly()
}

onMounted(() => {
  if (!show.value) return
  markSeen()
  document.documentElement.classList.add('db-splash')
  document.documentElement.style.overflow = 'hidden'   // 開場時首頁不能先被捲走，飛行終點才對得準
  window.addEventListener('keydown', skip)
  later(() => { revealed.value = true }, REVEAL_AT_MS)
})
onBeforeUnmount(() => { timers.forEach(clearTimeout); close() })
</script>

<template>
  <div
    v-if="show" class="splash" :class="{ 'is-revealed': revealed, 'is-flying': flying }"
    :style="{ '--fly': `${FLY_MS}ms` }" aria-hidden="true" @click="skip"
  >
    <div class="splash-bg" />
    <div class="splash-glow" />
    <div ref="logoEl" class="splash-logo" :style="flyStyle"><BrandIntro @done="later(fly, HOLD_MS)" /></div>
    <span class="splash-skip">點一下略過</span>
  </div>
</template>

<style scoped>
.splash {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  cursor: pointer;
}
.splash.is-flying { pointer-events: none; }

/* 白底淡出，首頁從後面浮現 */
.splash-bg {
  position: absolute;
  inset: 0;
  background: var(--db-card);
  transition: opacity 1.4s ease;
}
.is-revealed .splash-bg { opacity: 0; }
.is-flying .splash-bg { transition-duration: 0.4s; }

/* logo 後面留一圈柔光，首頁照片浮現時字還看得清楚；飛走時一起散掉 */
.splash-glow {
  position: absolute;
  width: min(820px, 120vw);
  aspect-ratio: 2 / 1;
  background: radial-gradient(closest-side, rgba(255, 255, 255, 0.92), rgba(255, 255, 255, 0.7) 55%, rgba(255, 255, 255, 0));
  transition: opacity calc(var(--fly) * 0.6) ease;
}
.is-flying .splash-glow { opacity: 0; }

.splash-logo {
  position: relative;
  width: min(460px, 72vw);
  transform-origin: 0 0;
  transition: transform var(--fly) cubic-bezier(0.65, 0, 0.2, 1), opacity var(--fly) ease;
}

.splash-skip {
  position: absolute;
  bottom: clamp(1.5rem, 5vh, 3rem);
  left: 50%;
  transform: translateX(-50%);
  color: var(--db-text-soft);
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  opacity: 0;
  animation: hint 0.6s ease 1.2s forwards;
  transition: opacity 0.3s;
}
.is-revealed .splash-skip { color: #fff; }
.is-flying .splash-skip { opacity: 0 !important; animation: none; }
@keyframes hint { to { opacity: 0.8; } }

/* 開場期間先藏起導覽列的 logo，飛過去的那個落定時才換回來，畫面上不會同時出現兩個 */
:global(html.db-splash .app-nav .brand img) { opacity: 0; }
</style>
