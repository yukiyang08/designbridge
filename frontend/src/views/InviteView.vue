<script setup>
/** 邀請連結落地頁：登入後（路由守衛處理）加入為共編者，再導去「我的設計」。 */
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authFetch } from '@/config/api'
import sceneBg from '@/assets/figma/room-bg.png'

const route = useRoute()
const router = useRouter()
const error = ref('')

onMounted(async () => {
  try {
    const res = await authFetch(`/api/invite/${encodeURIComponent(route.params.token)}`, { method: 'POST' })
    if (!res.ok) throw new Error(res.status)
    router.replace('/designs')
  } catch (e) {
    error.value = e.message === '404' ? '這個邀請連結已失效' : '加入失敗，請稍後再試'
  }
})
</script>

<template>
  <div class="db-scene" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <div class="db-card box">
      <p v-if="error" class="db-error">{{ error }}</p>
      <p v-else aria-busy="true">正在加入共編…</p>
      <router-link v-if="error" to="/designs" class="db-btn db-btn--sm">回我的設計</router-link>
    </div>
  </div>
</template>

<style scoped>
.box { margin: 4rem auto; padding: 2rem; max-width: 480px; text-align: center; display: flex; flex-direction: column; gap: 1rem; align-items: center; }
</style>
