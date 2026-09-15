<script setup>
import { RouterLink } from 'vue-router'
import logo from '../../../asset/designbridge_logo.png'

defineProps({
  // 深色底（首頁 hero）用白字，淺色底（流程頁）維持白字但加陰影才看得清楚
  tone: { type: String, default: 'light' },  // 'light' = 白字
})
</script>

<template>
  <header :class="['app-nav', `tone-${tone}`]">
    <RouterLink to="/" class="brand" aria-label="DesignBridge 首頁">
      <img :src="logo" alt="DesignBridge" />
    </RouterLink>
    <nav class="links">
      <RouterLink to="/">首頁</RouterLink>
      <RouterLink to="/account">個人專區</RouterLink>
    </nav>
  </header>
</template>

<style scoped>
.app-nav {
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
  gap: 1.75rem;
}

.links a {
  font-family: var(--db-font-display);
  font-style: italic;
  font-size: 1.25rem;
  color: #fff;
  text-decoration: none;
  text-shadow: 0 1px 6px rgba(0, 0, 0, 0.45);
  transition: color 0.16s;
}
.links a:hover,
.links a.router-link-exact-active { color: var(--db-accent); }

@media (max-width: 720px) {
  .app-nav { gap: 1rem; padding: 0.5rem 0.75rem; }
  .brand img { height: 44px; }
  .links { gap: 1rem; }
  .links a { font-size: 1rem; }
}
</style>
