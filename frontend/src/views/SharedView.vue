<script setup>
/** 唯讀分享頁：不用登入，只看設計的標題、各空間目前那一版的圖與描述。 */
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { apiUrl } from '@/config/api'
import sceneBg from '@/assets/figma/room-bg.png'

const route = useRoute()
const data = ref(null)
const error = ref('')
const activeIdx = ref(0)
const active = computed(() => data.value?.spaces[activeIdx.value] || null)

// 同一個頁面換 token（瀏覽器上一頁／下一頁）時要重新載入
watch(() => route.params.token, async token => {
  data.value = null
  error.value = ''
  activeIdx.value = 0
  try {
    const res = await fetch(apiUrl(`/api/shared/${encodeURIComponent(token)}`))
    if (!res.ok) throw new Error(res.status)
    const body = await res.json()
    if (token === route.params.token) data.value = body
  } catch (e) {
    error.value = e.message === '404' ? '這個分享連結已失效' : '無法載入設計'
  }
}, { immediate: true })
</script>

<template>
  <div class="db-scene" :style="{ '--db-scene-image': `url(${sceneBg})` }">
    <div class="db-card shared">
      <header class="head">
        <h1 class="title">{{ data?.title || 'DesignBridge' }}</h1>
        <router-link to="/" class="db-btn db-btn--ghost db-btn--sm">我也要設計</router-link>
      </header>

      <p v-if="error" class="db-error">{{ error }}</p>
      <p v-else-if="!data" class="hint" aria-busy="true">載入中…</p>
      <p v-else-if="!data.spaces.length" class="hint">這個設計還沒有完成的圖</p>

      <template v-else>
        <div v-if="data.spaces.length > 1" class="tabs">
          <button
            v-for="(s, i) in data.spaces" :key="i" type="button"
            :class="['tab', { on: i === activeIdx }]" @click="activeIdx = i"
          >{{ s.name }}</button>
        </div>
        <img v-if="active.image_url" :src="active.image_url" alt="" class="main-img" />
        <p v-if="active.prompt" class="prompt">{{ active.prompt }}</p>
        <p v-if="active.style" class="hint">{{ active.style }}</p>
        <img v-if="active.pano_url" :src="active.pano_url" alt="環景" class="main-img pano" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.shared { margin: 1.25rem auto 3rem; padding: 1.75rem 1.5rem 2.5rem; max-width: 900px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1.25rem; }
.title { margin: 0; font-family: var(--db-font-display); font-style: italic; font-weight: 500; font-size: 1.6rem; color: var(--db-text); }
.hint { color: var(--db-text-soft); font-size: 0.9rem; }
.prompt { line-height: 1.6; color: var(--db-text); }
.tabs { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
.tab { padding: 0.35rem 1rem; border: 1px solid #d8d4cb; border-radius: var(--db-radius-pill); background: #fff; color: var(--db-text); cursor: pointer; }
.tab.on { background: var(--db-accent); border-color: var(--db-accent); color: var(--db-on-accent); }
.main-img { width: 100%; border-radius: var(--db-radius-chip); display: block; margin-bottom: 0.8rem; }
.pano { margin-top: 1rem; }
</style>
