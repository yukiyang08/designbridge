import { ref, computed, watch } from 'vue'
import { authFetch } from '@/config/api'
import { useAuth } from './useAuth'

// 模組層級的共享狀態：跨頁面（HomeView / FurnitureView）保留使用者已勾選的家具
const selectedFurniture = ref([])

// 登入者的家具收藏存在後端（furniture_favorites）：登入後載入，之後每次變動整份覆寫回去
// 雲端同步還沒做好，先關閉：收藏只存在記憶體，重新整理就清空
const FAVORITES_SYNC = false
const { user } = useAuth()
// 最後一次與雲端一致的內容（JSON）；null = 還沒載入成功，不回寫，避免空清單蓋掉雲端資料
let synced = null
// 只看 id：切回分頁、token 更新時 Supabase 會換一個新的 user 物件，看整個物件會一直重抓
watch(() => user.value?.id, async id => {
  synced = null
  if (!id) { selectedFurniture.value = []; return }
  if (!FAVORITES_SYNC) return
  try {
    const res = await authFetch('/api/furniture-favorites')
    if (res.ok) {
      const items = await res.json()
      synced = JSON.stringify(items)
      selectedFurniture.value = items
    }
  } catch { /* 離線時只在記憶體內操作 */ }
}, { immediate: true })

watch(selectedFurniture, items => {
  if (synced === null) return
  const json = JSON.stringify(items)
  if (json === synced) return   // 剛從雲端載入的內容不用寫回去
  synced = json
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
