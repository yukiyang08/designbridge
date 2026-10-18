import { getAccessToken } from '@/composables/useAuth'

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export function apiUrl(path) {
  return `${API_BASE}${path}`
}

// 收斂重複的 POST/PATCH + JSON header + JSON.stringify 樣板；回傳原始 Response，
// 呼叫端仍自行處理 res.ok / 例外訊息（各步驟的錯誤處理不盡相同，故意不在這裡吃掉）。
export async function authFetch(path, opts = {}) {
  const token = await getAccessToken()
  return fetch(apiUrl(path), {
    ...opts,
    headers: { ...opts.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  })
}

export function jsonFetch(path, data, method = 'POST', signal) {
  return authFetch(path, {
    method,
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function mediaUrl(path) {
  if (!path) return ''
  const normalized = path.replace(/\\/g, '/')
  if (normalized.startsWith('http://') || normalized.startsWith('https://')) return normalized
  return `${API_BASE}/${normalized}`
}
