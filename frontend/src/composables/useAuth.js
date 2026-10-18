import { ref } from 'vue'
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
)

// 模組層級單例：所有元件共用同一份登入狀態
const user = ref(null)
const ready = supabase.auth.getSession().then(({ data }) => {
  user.value = data.session?.user ?? null
})
supabase.auth.onAuthStateChange((_e, session) => {
  user.value = session?.user ?? null
})

export async function getAccessToken() {
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

export function useAuth() {
  return {
    user,
    ready,
    signInWithGoogle: (next = '/account') =>
      supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: window.location.origin + next },
      }),
    signOut: () => supabase.auth.signOut(),
  }
}
