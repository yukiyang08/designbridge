import { hasDraft } from '../composables/design-flow/state'
import { createRouter, createWebHistory } from 'vue-router'
import HeroView from '../views/HeroView.vue'
import StartView from '../views/StartView.vue'
import StudioView from '../views/StudioView.vue'
import AccountView from '../views/AccountView.vue'
import HistoryView from '../views/HistoryView.vue'
import FurnitureView from '../views/FurnitureView.vue'
import CartView from '../views/CartView.vue'

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

    // ── 既有頁面，維持原樣 ──
    { path: '/history',   name: 'history',   component: HistoryView },
    { path: '/furniture', name: 'furniture', component: FurnitureView },
    { path: '/cart',      name: 'cart',      component: CartView },

    // 獨立的房型配置 CAD 平面圖工具（輸入幾房幾廳生成牆／門／窗配置圖），跟主精靈流程無關。
    { path: '/room-plan', name: 'room-plan', component: () => import('../views/RoomPlanView.vue') },
  ],
})

// 直接輸入 /studio（沒經過入口頁選路徑）會得到一個空流程，導回入口頁。
router.beforeEach(to => (to.name === 'studio' && !hasDraft() ? { name: 'start' } : true))

export default router
