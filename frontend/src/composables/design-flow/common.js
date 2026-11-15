import { authFetch } from '@/config/api'

export async function uploadFile(file) {
  const body = new FormData()
  body.append('file', file)
  const res = await authFetch('/api/upload-image', { method: 'POST', body })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `${res.status}`)
  return (await res.json()).path
}
