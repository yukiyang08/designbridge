import { ref, computed, watch } from 'vue'
import { authFetch } from '@/config/api'
import { useAuth } from './useAuth'

// 模組層級的共享狀態：跨頁面（HomeView / FurnitureView）保留使用者已勾選的家具
const selectedFurniture = ref([])

// 登入者的家具收藏存在後端（furniture_favorites）：登入後載入，之後每次變動整份覆寫回去
const { user } = useAuth()
let loaded = false
watch(user, async u => {
  loaded = false
  if (!u) { selectedFurniture.value = []; return }
  try {
    const res = await authFetch('/api/furniture-favorites')
    if (res.ok) selectedFurniture.value = await res.json()
    loaded = true   // 載入成功前不回寫，避免空清單蓋掉雲端資料
  } catch { /* 離線時只在記憶體內操作 */ }
}, { immediate: true })

watch(selectedFurniture, items => {
  if (!loaded) return
  authFetch('/api/furniture-favorites', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  }).catch(() => {})
}, { deep: true })

function itemKey(item) {
  return item.id || item.url || `${item.name}__${item.category}`
}

function isSelected(item) {
  const key = itemKey(item)
  return selectedFurniture.value.some(f => itemKey(f) === key)
}

function toggle(item) {
  if (isSelected(item)) {
    const key = itemKey(item)
    selectedFurniture.value = selectedFurniture.value.filter(f => itemKey(f) !== key)
  } else {
    selectedFurniture.value = [
      ...selectedFurniture.value,
      {
        id: item.id,
        name: item.name,
        category: item.category,
        price: item.price,
        currency: item.currency,
        url: item.url,
        image_url: item.image_url,
      },
    ]
  }
}

function remove(item) {
  const key = itemKey(item)
  selectedFurniture.value = selectedFurniture.value.filter(f => itemKey(f) !== key)
}

function clear() {
  selectedFurniture.value = []
}

export function useFurnitureSelection() {
  return {
    selectedFurniture,
    selectedCount: computed(() => selectedFurniture.value.length),
    isSelected,
    toggle,
    remove,
    clear,
  }
}
