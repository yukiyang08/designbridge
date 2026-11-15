import { ref, computed, watch } from 'vue'
import { authFetch } from '@/config/api'
import { useAuth } from './useAuth'

// 收藏也存一份在這台瀏覽器（localStorage）：未登入時用它，登入時拿來跟雲端合併
const STORAGE_KEY = 'db.furniture-favorites'
// 本機那份屬於哪個帳號：同一人的只是雲端快取，登入時以雲端為準，否則別台刪掉的會被併回來
const OWNER_KEY = 'db.furniture-favorites.owner'
function setOwner(id) {
  try { id ? localStorage.setItem(OWNER_KEY, id) : localStorage.removeItem(OWNER_KEY) } catch { /* 寫不進去就每次合併 */ }
}
function getOwner() {
  try { return localStorage.getItem(OWNER_KEY) } catch { return null }
}
function loadLocal() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [] } catch { return [] }
}

// 模組層級的共享狀態：跨頁面（HomeView / FurnitureView）保留使用者已勾選的家具
const selectedFurniture = ref(loadLocal())
watch(selectedFurniture, items => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(items)) } catch { /* 無痕模式等寫不進去：只留在記憶體 */ }
}, { deep: true })

// 登入者的家具收藏同步到後端（furniture_favorites）：登入時跟本機合併，之後變動停 0.4 秒整份覆寫
const { user } = useAuth()
// 最後一次與雲端一致的內容（JSON）；null = 還沒載入成功，不回寫，避免空清單蓋掉雲端資料
let synced = null
let pushTimer = null
// 只看 id：切回分頁、token 更新時 Supabase 會換一個新的 user 物件，看整個物件會一直重抓
watch(() => user.value?.id, async (id, prevId) => {
  synced = null
  clearTimeout(pushTimer)
  if (!id) {
    // 只有真的登出才清（共用電腦別留給下一個人）；剛載入時 user 還沒還原也是 undefined，不能清
    if (prevId) { selectedFurniture.value = []; setOwner(null) }
    return
  }
  try {
    const res = await authFetch('/api/furniture-favorites')
    if (!res.ok || user.value?.id !== id) return
    const cloud = await res.json()
    synced = JSON.stringify(cloud)
    // 登入前（未登入時）在本機收藏的不能被雲端蓋掉：合併後若有新增，下面的 watch 會寫回雲端
    const keys = new Set(cloud.map(itemKey))
    const local = getOwner() === id ? [] : selectedFurniture.value.filter(f => !keys.has(itemKey(f)))
    selectedFurniture.value = [...cloud, ...local]
    setOwner(id)
  } catch { /* 離線：只存本機，下次登入再合併 */ }
}, { immediate: true })

watch(selectedFurniture, items => {
  if (synced === null) return
  clearTimeout(pushTimer)
  // 連點多下時只送最後一份，避免多個 PUT 先後順序錯亂互相覆蓋
  pushTimer = setTimeout(() => {
    const json = JSON.stringify(items)
    if (json === synced) return   // 剛從雲端載入的內容不用寫回去
    synced = json
    authFetch('/api/furniture-favorites', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }).catch(() => {})
  }, 400)
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
        brand: item.brand,
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
