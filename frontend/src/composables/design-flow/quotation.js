import { jsonFetch } from '@/config/api'
import { useFurnitureSelection } from '@/composables/useFurnitureSelection'
import {
  lastGeneratedImage, result, quotationLoading, quotationError,
  cadActiveRoomId, cadRoomSnapshots, cadQuoting,
} from './state'

// 一份報價的總價：每件家具取目前選中的候選（selected_indices 由結果頁換款時寫回，沒有就是第 0 個）
export function quotationTotal(q) {
  return (q?.furniture_list || []).reduce(
    (sum, item, idx) => sum + (item.candidates?.[q.selected_indices?.[idx] ?? 0]?.price ?? 0), 0,
  )
}

/* ══ Step: 預算估計 ══════════════════════════════════════ */

// 估價要辨識畫面上的家具，約 30–40 秒。這段時間使用者很可能又微調、換風格、切去別間房，
// 所以每一輪記下「是哪一張圖」：新的一輪開始，舊的就作廢；回來時圖已經不是送出去的那張，就丟掉不寫入。
// 不然舊圖的家具推薦會被寫進新的結果，而且新的圖還會因為「已經有報價」而不再自動估價。
let quotationSeq = 0
let inflightPath = null

export async function fetchQuotation() {
  const imagePath = lastGeneratedImage.value?.path || result.value?.generated_image_path
  if (!imagePath) return
  if (quotationLoading.value && inflightPath === imagePath) return   // 這張圖已經在估價了
  const seq = ++quotationSeq
  inflightPath = imagePath
  const { selectedFurniture } = useFurnitureSelection()
  quotationLoading.value = true
  quotationError.value = ''
  try {
    const res = await jsonFetch('/api/quotation', {
      image_path: imagePath,
      structured_requirement: result.value?.structured_requirement || null,
      selected_furniture: selectedFurniture.value,
      task_id: result.value?.task_id || null,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (!data) throw new Error('沒有辨識到畫面中的家具')   // 寫進 null 會讓「沒有報價就自動估價」的判斷一直成立
    if (seq !== quotationSeq) return   // 有更新的一輪估價了
    const current = lastGeneratedImage.value?.path || result.value?.generated_image_path
    if (current !== imagePath) return  // 畫面上已經是別張圖，這份報價是舊圖的
    // 估價耗時接在 timing_runs 後面（重新估價則取代上一筆）
    let runs = result.value?.timing_runs || []
    if (runs.at(-1)?.kind === 'quotation') runs = runs.slice(0, -1)
    if (data.timing_run) runs = [...runs, data.timing_run]
    result.value = { ...(result.value || {}), quotation_result: data, timing_runs: runs }
  } catch (e) {
    if (seq === quotationSeq) quotationError.value = e.message || '估價失敗，請稍後再試'
  } finally {
    if (seq === quotationSeq) { quotationLoading.value = false; inflightPath = null }
  }
}

// 整層總覽：幫「不是目前這間」的房間估價，結果寫回它自己的快照。
// 目前這間走原本的 fetchQuotation（寫進全域 result）。
async function quoteRoom(roomId) {
  if (roomId === cadActiveRoomId.value) return fetchQuotation()
  const snap = cadRoomSnapshots.value[roomId]
  const imagePath = snap?.lastGeneratedImage?.path || snap?.result?.generated_image_path
  if (!imagePath || snap?.result?.quotation_result || cadQuoting.value[roomId]) return
  cadQuoting.value = { ...cadQuoting.value, [roomId]: true }
  try {
    const { selectedFurniture } = useFurnitureSelection()
    const res = await jsonFetch('/api/quotation', {
      image_path: imagePath,
      structured_requirement: snap.result?.structured_requirement || null,
      selected_furniture: selectedFurniture.value,
      task_id: snap.result?.task_id || null,
    })
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (!data) return
    const cur = cadRoomSnapshots.value[roomId]   // 估價期間這間可能又被重新生成：圖不是送出去的那張就丟掉
    if ((cur?.lastGeneratedImage?.path || cur?.result?.generated_image_path) !== imagePath) return
    cadRoomSnapshots.value = {
      ...cadRoomSnapshots.value,
      [roomId]: { ...cur, result: { ...cur.result, quotation_result: data } },
    }
  } catch (e) {
    quotationError.value = e.message || '估價失敗，請稍後再試'
  } finally {
    const { [roomId]: _q, ...rest } = cadQuoting.value
    cadQuoting.value = rest
  }
}

// 一次估多間：估價每間約 30–40 秒，同時 3 條（後端是執行緒池，再多會互相搶 CLIP 模型）
export async function quoteRooms(roomIds, concurrency = 3) {
  const queue = [...roomIds]
  const worker = async () => { for (let id = queue.shift(); id; id = queue.shift()) await quoteRoom(id) }
  await Promise.all(Array.from({ length: Math.min(concurrency, queue.length) }, worker))
}
