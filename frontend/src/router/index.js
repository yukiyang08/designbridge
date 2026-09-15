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

    // 深色行銷展示頁。沒有入口連過去，需要時直接打網址（維持改版前的狀態）。
    { path: '/landing', name: 'landing', component: () => import('../views/LandingView.vue') },

    // 舊版側欄工作台。新版精靈涵蓋了同樣的功能，這條路留著是為了改版期間可以
    // 兩邊對照、確認沒有漏掉行為；確認無虞之後可以連同 HomeView.vue 一起移除。
    { path: '/classic', name: 'classic', component: () => import('../views/HomeView.vue') },
  ],
})

export default router
