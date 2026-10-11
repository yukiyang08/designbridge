import { ref, onMounted, onBeforeUnmount } from 'vue'

export const seg = (p, a, b) => Math.min(1, Math.max(0, (p - a) / (b - a)))

export const prefersReducedMotion = () =>
  typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * 元素捲過視窗的進度 0..1（給 sticky 區塊用：總行程 = 元素高度 − 視窗高度）。
 * 減少動態時固定回 1，直接呈現最終畫面。
 */
export function useScrollProgress(elRef) {
  const p = ref(0)
  let raf = 0

  function update() {
    raf = 0
    const el = elRef.value
    if (!el) return
    const r = el.getBoundingClientRect()
    const total = r.height - window.innerHeight
    p.value = total > 0 ? Math.min(1, Math.max(0, -r.top / total)) : 1
  }
  function onScroll() {
    if (!raf) raf = requestAnimationFrame(update)
  }

  onMounted(() => {
    if (prefersReducedMotion()) { p.value = 1; return }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    update()
  })
  onBeforeUnmount(() => {
    window.removeEventListener('scroll', onScroll)
    window.removeEventListener('resize', onScroll)
    cancelAnimationFrame(raf)
  })
  return p
}
