import { apiUrl } from '@/config/api'
import {
  STYLE_PAGE_SIZE, ROOM_TYPE_LABEL, timers,
  styleRefImage, extraPrompt, roomTypeForPlan, selectedStyle,
  styleOptions, styleLoading, styleError,
  styleCandidates, styleCandidatePool, candidatesLoading, candidatesSearched,
  confirmedStyle, matchedStylePreview, styleDemoImages,
} from './state'

async function waitForBackend(maxWaitMs = 120000, intervalMs = 2000) {
  const deadline = Date.now() + maxWaitMs
  while (Date.now() < deadline) {
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 4000)
      const res = await fetch(apiUrl('/api/health'), { signal: ctrl.signal })
      clearTimeout(timer)
      if (res.ok) return true
    } catch {}
    styleError.value = '等待後端啟動中…（請確認已執行 python -m uvicorn api:app）'
    await new Promise(r => setTimeout(r, intervalMs))
  }
  return false
}

export async function fetchStyleOptions() {
  styleLoading.value = true
  styleError.value = ''
  if (!(await waitForBackend())) {
    styleError.value = '無法連線後端，請確認伺服器是否已啟動'
    styleLoading.value = false
    return
  }
  try {
    const res = await fetch(apiUrl('/api/style-profiles'))
    if (!res.ok) throw new Error('載入風格選項失敗')
    const data = await res.json()
    styleOptions.value = [
      { label: '自動', value: 'auto' },
      ...data.map(({ style_name, style_id }) => ({ label: `${style_name} (${style_id})`, value: style_id })),
    ]
    styleError.value = ''
  } catch { styleError.value = '無法載入風格選項，請稍後重試' }
  finally { styleLoading.value = false }
}

/* ══ 每個風格一張示範圖（一鍵換風格還沒生成過的卡片用）══════ */

export async function fetchStyleDemoImages() {
  if (Object.keys(styleDemoImages.value).length) return  // 一次就夠，不用每次進結果頁都重打
  try {
    const res = await fetch(apiUrl('/api/style-search?query=&style_id=&top_k=24&diverse=true'))
    if (!res.ok) return
    const data = await res.json()
    const map = {}
    for (const c of Array.isArray(data) ? data : []) {
      if (c.style_id && !map[c.style_id]) map[c.style_id] = c.image_url
    }
    styleDemoImages.value = map
  } catch {}
}

/* ══ 風格搜尋（沿用舊 HomeView 的錨定／輪替行為） ══════════ */

export async function fetchStyleCandidates({ anchorSelected = false } = {}) {
  if (styleRefImage.file) return
  const anchor = anchorSelected ? confirmedStyle.value : null
  const q = anchor ? '' : (extraPrompt.value.trim() || ROOM_TYPE_LABEL[roomTypeForPlan.value] || '')
  const sid = anchor ? anchor.style_id : (selectedStyle.value !== 'auto' ? selectedStyle.value : '')
  if (!q && !sid) {
    styleCandidates.value = []
    candidatesSearched.value = false
    confirmedStyle.value = null
    matchedStylePreview.value = null
    return
  }
  candidatesLoading.value = true
  const diverse = !anchor && !extraPrompt.value.trim() && !sid
  try {
    const res = await fetch(
      apiUrl(`/api/style-search?query=${encodeURIComponent(q)}&style_id=${encodeURIComponent(sid)}&top_k=24${diverse ? '&diverse=true' : ''}`),
    )
    if (res.ok) {
      const data = await res.json()
      let pool = (Array.isArray(data) ? data : [])
        .slice().sort((a, b) => Number(b?.similarity ?? 0) - Number(a?.similarity ?? 0))
      if (anchor) pool = [anchor, ...pool.filter(c => c.image_url !== anchor.image_url)]
      styleCandidatePool.value = pool
      const sorted = pool.slice(0, STYLE_PAGE_SIZE)
      styleCandidates.value = sorted
      matchedStylePreview.value = sorted[0]
        ? { image_url: sorted[0].image_url, style_name: sorted[0].style_name, similarity: sorted[0].similarity }
        : null
      const keep = confirmedStyle.value && sorted.find(c => c.image_url === confirmedStyle.value.image_url)
      confirmedStyle.value = keep || (!diverse && sorted[0]) || null
    }
  } catch {}
  finally { candidatesLoading.value = false; candidatesSearched.value = true }
}

export function showNextRound() {
  const pool = styleCandidatePool.value
  if (pool.length <= STYLE_PAGE_SIZE) return
  const rotated = [...pool.slice(STYLE_PAGE_SIZE), ...pool.slice(0, STYLE_PAGE_SIZE)]
  styleCandidatePool.value = rotated
  styleCandidates.value = rotated.slice(0, STYLE_PAGE_SIZE)
}

export function scheduleSearch() {
  clearTimeout(timers.search)
  styleCandidates.value = []
  styleCandidatePool.value = []
  candidatesSearched.value = false
  confirmedStyle.value = null
  matchedStylePreview.value = null
  timers.search = setTimeout(fetchStyleCandidates, 600)
}

export function confirmStyle(candidate) { confirmedStyle.value = candidate }
export function clearConfirmedStyle()   { confirmedStyle.value = null }
