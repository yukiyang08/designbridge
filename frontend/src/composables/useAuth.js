import { ref } from 'vue'
import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// 沒設定 frontend/.env 時 createClient 會直接丟錯，整個前端白屏；改成登入功能停用、其他照常
export const authEnabled = Boolean(url && anonKey)
if (!authEnabled) {
  console.warn('[auth] 未設定 VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY（frontend/.env），登入功能停用')
}
const supabase = authEnabled ? createClient(url, anonKey) : null

// 模組層級單例：所有元件共用同一份登入狀態
const user = ref(null)
const ready = supabase
  ? supabase.auth.getSession().then(({ data }) => {
    user.value = data.session?.user ?? null
  })
  : Promise.resolve()
supabase?.auth.onAuthStateChange((_e, session) => {
  user.value = session?.user ?? null
})

export async function getAccessToken() {
  if (!supabase) return null
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

export function useAuth() {
  return {
    user,
    ready,
    signInWithGoogle: (next = '/account') =>
      supabase?.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: window.location.origin + next },
      }),
    signOut: () => supabase?.auth.signOut(),
  }
}
