import { computed, ref, watch } from 'vue'
import { authFetch } from '@/config/api'
import { useAuth } from '@/composables/useAuth'

// 模組層級快取：換帳號才重問 /api/me，導覽列、結果頁、路由守衛共用。只決定畫面顯示，權限在後端
const me = ref(null)
const isAdmin = computed(() => me.value?.role === 'admin')
const { user } = useAuth()

let seq = 0
let pending = Promise.resolve(null)

function loadMe() {
  const mine = ++seq
  if (!user.value) {
    me.value = null
    pending = Promise.resolve(null)
    return pending
  }
  pending = authFetch('/api/me')
    .then(r => (r.ok ? r.json() : null))
    .catch(() => null)
    .then(data => {
      if (mine === seq) me.value = data   // 較晚回來的舊帳號回應不能蓋掉現在的
      return mine === seq ? data : pending
    })
  return pending
}

// 只看 id：token 更新會換掉 user 物件但人沒變，不重問也不讓管理員介面閃掉
// sync：路由守衛 await ready 後馬上要拿到這次的 pending
watch(() => user.value?.id, () => { me.value = null; loadMe() }, { immediate: true, flush: 'sync' })

export function useMe() {
  return {
    me,
    isAdmin,
    meReady: () => pending,
    refreshMe: loadMe,   // 點數等會變的資料要最新值時用
  }
}
