<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import logo from '../../../asset/designbridge_logo.png'

const { user, signInWithGoogle, signOut } = useAuth()

defineProps({
  // 深色底（首頁 hero）用白字，淺色底（流程頁）維持白字但加陰影才看得清楚
  tone: { type: String, default: 'light' },  // 'light' = 白字
})

const menuOpen = ref(false)
const navOpen = ref(false)   // 手機漢堡選單
const route = useRoute()
watch(() => route.fullPath, () => { navOpen.value = false; menuOpen.value = false })
const menuEl = ref(null)
const displayName = computed(() => user.value?.user_metadata?.name || user.value?.email || '')
const initial = computed(() => (displayName.value[0] || '?').toUpperCase())

function onDocClick(e) {
  navOpen.value = false   // 漢堡鈕與選單本身都有 @click.stop，走到這裡一定是點在外面
  if (menuEl.value && !menuEl.value.contains(e.target)) menuOpen.value = false
}
function onKey(e) {
  if (e.key === 'Escape') { navOpen.value = false; menuOpen.value = false }
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <header :class="['app-nav', `tone-${tone}`]">
    <RouterLink to="/" class="brand" aria-label="DesignBridge 首頁">
      <img :src="logo" alt="DesignBridge" />
    </RouterLink>

    <nav class="links">
      <RouterLink to="/">首頁</RouterLink>
      <RouterLink to="/furniture">家具查詢</RouterLink>
    </nav>

    <nav class="links right">
      <RouterLink to="/designs">我的設計</RouterLink>

      <div v-if="user" ref="menuEl" class="user-menu">
        <button
          type="button" class="avatar" :aria-expanded="menuOpen" aria-label="帳號選單"
          @click="menuOpen = !menuOpen"
        >
          <img
            v-if="user.user_metadata?.avatar_url"
            :src="user.user_metadata.avatar_url" referrerpolicy="no-referrer" alt=""
          />
          <span v-else>{{ initial }}</span>
        </button>
        <div v-if="menuOpen" class="dropdown" @click="menuOpen = false">
          <div class="who">
            <strong>{{ displayName }}</strong>
            <small v-if="user.user_metadata?.name">{{ user.email }}</small>
          </div>
          <RouterLink to="/account">個人專區</RouterLink>
          <button type="button" @click="signOut">登出</button>
        </div>
      </div>
      <button v-else type="button" class="login-btn" @click="signInWithGoogle()">登入</button>
    </nav>

    <button
      type="button" class="burger" :aria-expanded="navOpen" aria-label="開啟選單"
      @click.stop="navOpen = !navOpen"
    >
      <span></span><span></span><span></span>
    </button>

    <Transition name="drawer">
      <div v-if="navOpen" class="drawer-wrap">
        <div class="backdrop" @click="navOpen = false"></div>
        <aside class="mobile-menu" @click.stop>
          <button type="button" class="m-close" aria-label="關閉選單" @click="navOpen = false">✕</button>
          <RouterLink to="/">首頁</RouterLink>
          <RouterLink to="/furniture">家具查詢</RouterLink>
          <RouterLink to="/designs">我的設計</RouterLink>
          <template v-if="user">
            <RouterLink to="/account">個人專區</RouterLink>
            <div class="m-who">{{ displayName }}</div>
            <button type="button" @click="signOut">登出</button>
          </template>
          <button v-else type="button" @click="signInWithGoogle()">Google 登入</button>
        </aside>
      </div>
    </Transition>
  </header>
</template>

<style scoped>
.app-nav {
  position: relative;
  display: flex;
  align-items: center;
  gap: 2rem;
  padding: 0.5rem 1.25rem;
}

.brand img {
  display: block;
  height: 60px;
  width: auto;
}

.links {
  display: flex;
  align-items: center;
  gap: 1.75rem;
}
.links.right { margin-left: auto; }

.links > a {
  font-family: var(--db-font-display);
  font-style: normal;
  font-size: 1.25rem;
  color: #fff;
  text-decoration: none;
  text-shadow: 0 1px 6px rgba(0, 0, 0, 0.45);
  padding-bottom: 2px;
  border-bottom: 2px solid transparent;
  transition: color 0.16s, border-color 0.16s;
}
.links > a:hover,
.links > a.router-link-exact-active { color: var(--db-accent); border-bottom-color: var(--db-accent); }

.login-btn {
  padding: 0.4rem 1.2rem;
  border: 1.5px solid #fff;
  border-radius: var(--db-radius-pill);
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  font-size: 0.95rem;
  cursor: pointer;
  backdrop-filter: blur(4px);
  transition: background 0.16s, color 0.16s;
}
.login-btn:hover { background: #fff; color: var(--db-text); }

.user-menu { position: relative; }
.avatar {
  display: flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; padding: 0;
  border: 2px solid #fff; border-radius: 50%; overflow: hidden;
  background: var(--db-accent); color: #fff; font-size: 1.1rem;
  cursor: pointer;
}
.avatar img { width: 100%; height: 100%; object-fit: cover; }

.dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 20;
  min-width: 200px;
  padding: 0.4rem;
  background: var(--db-card);
  border-radius: var(--db-radius-chip);
  box-shadow: var(--db-shadow-card);
}
.dropdown .who {
  display: flex; flex-direction: column; gap: 2px;
  padding: 0.5rem 0.7rem 0.6rem;
  border-bottom: 1px solid #efefef;
  margin-bottom: 0.3rem;
  color: var(--db-text);
  font-size: 0.9rem;
  word-break: break-all;
}
.dropdown .who small { color: var(--db-text-soft); }
.dropdown a,
.dropdown button {
  display: block; width: 100%;
  padding: 0.5rem 0.7rem;
  border: 0; border-radius: 8px;
  background: none; text-align: left;
  color: var(--db-text); font-size: 0.92rem; text-decoration: none;
  cursor: pointer;
}
.dropdown a:hover,
.dropdown button:hover { background: var(--db-chip-soft); }

.burger { display: none; }
.drawer-wrap { display: none; }

@media (max-width: 720px) {
  .app-nav { gap: 0.75rem; padding: 0.5rem 0.75rem; justify-content: space-between; }
  .brand img { height: 44px; }
  .links { display: none; }

  .burger {
    display: flex; flex-direction: column; justify-content: center; gap: 5px;
    width: 44px; height: 44px; padding: 0 10px;
    border: 0; border-radius: 10px; background: rgba(0, 0, 0, 0.35); cursor: pointer;
  }
  .burger span { display: block; height: 2px; border-radius: 2px; background: #fff; }

  /* 從右側滑出的抽屜；backdrop 蓋住頁面並接住點擊 */
  .drawer-wrap { display: block; position: fixed; inset: 0; z-index: 100; }
  .backdrop { position: absolute; inset: 0; background: rgba(0, 0, 0, 0.5); }
  .mobile-menu {
    position: absolute; top: 0; right: 0; bottom: 0;
    display: flex; flex-direction: column;
    width: min(300px, 80vw); padding: 0.75rem; overflow-y: auto;
    background: var(--db-card); box-shadow: -8px 0 24px rgba(0, 0, 0, 0.25);
  }
  .m-close {
    align-self: flex-end; width: 44px !important; height: 44px; padding: 0 !important;
    text-align: center !important; font-size: 1.1rem !important; color: var(--db-text-soft) !important;
  }
  .drawer-enter-active, .drawer-leave-active { transition: opacity 0.22s; }
  .drawer-enter-active .mobile-menu, .drawer-leave-active .mobile-menu { transition: transform 0.22s ease; }
  .drawer-enter-from, .drawer-leave-to { opacity: 0; }
  .drawer-enter-from .mobile-menu, .drawer-leave-to .mobile-menu { transform: translateX(100%); }
  .mobile-menu a, .mobile-menu button {
    display: block; width: 100%; padding: 0.85rem 1rem; border: 0; border-radius: 8px;
    background: none; text-align: left; text-decoration: none; cursor: pointer;
    color: var(--db-text); font-family: var(--db-font-display); font-size: 1.1rem;
  }
  .mobile-menu a:hover, .mobile-menu button:hover,
  .mobile-menu a.router-link-exact-active { background: var(--db-chip-soft); }
  .m-who {
    margin-top: 0.3rem; padding: 0.6rem 1rem 0.2rem; border-top: 1px solid #efefef;
    font-size: 0.85rem; color: var(--db-text-soft); word-break: break-all;
  }
}
</style>
