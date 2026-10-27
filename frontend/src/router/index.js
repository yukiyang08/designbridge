import { hasDraft } from '../composables/design-flow/state'
import { useAuth, authEnabled } from '../composables/useAuth'
import { createRouter, createWebHistory } from 'vue-router'
import HeroView from '../views/HeroView.vue'
import StartView from '../views/StartView.vue'
import StudioView from '../views/StudioView.vue'
import AccountView from '../views/AccountView.vue'
import MyDesignsView from '../views/MyDesignsView.vue'
import FurnitureView from '../views/FurnitureView.vue'
import CartView from '../views/CartView.vue'
import SharedView from '../views/SharedView.vue'
import InviteView from '../views/InviteView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash }
    return { top: 0 }
  },
  routes: [
    // ── Figma 設計的主動線：首頁 → 入口三選一 → 線性精靈 ──
    { path: '/',        name: 'home',    component: HeroView },
    { path: '/start',   name: 'start',   component: StartView },
    { path: '/studio',  name: 'studio',  component: StudioView },
    { path: '/account', name: 'account', component: AccountView },

    // 我的設計：登入者每次生成的設計（即歷史紀錄）
    { path: '/designs',   name: 'designs',   component: MyDesignsView },
    { path: '/furniture', name: 'furniture', component: FurnitureView },
    { path: '/cart',      name: 'cart',      component: CartView },
    // 分享：唯讀頁不用登入；邀請連結要先登入才能加入共編
    { path: '/s/:token',      name: 'shared', component: SharedView },
    { path: '/invite/:token', name: 'invite', component: InviteView },

    // 獨立的房型配置 CAD 平面圖工具（輸入幾房幾廳生成牆／門／窗配置圖），跟主精靈流程無關。
    { path: '/room-plan', name: 'room-plan', component: () => import('../views/RoomPlanView.vue') },
  ],
})

// 直接輸入 /studio（沒經過入口頁選路徑）會得到一個空流程，導回入口頁。
router.beforeEach(to => (to.name === 'studio' && !hasDraft() ? { name: 'start' } : true))

// 需要登入的頁面：未登入就導去 Google 登入，登入後回到原頁（會整頁重載，所以守在 /start 而非 /studio）
const AUTH_PAGES = ['start', 'account', 'designs', 'cart', 'invite']
router.beforeEach(async to => {
  if (!AUTH_PAGES.includes(to.name)) return true
  // 本機沒設定 Supabase 時不擋，否則會被導去一個無法完成的登入
  if (!authEnabled) return true
  const { user, ready, signInWithGoogle } = useAuth()
  await ready
  if (user.value) return true
  signInWithGoogle(to.fullPath)
  return false
})

export default router
