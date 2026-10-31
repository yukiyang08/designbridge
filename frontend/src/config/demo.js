// DEMO 模式：使用範例照片時，生成與換風格直接回傳預先生成的圖，不打後端
import { ref } from 'vue'
import detectRooms from './demoDetectRooms.json'
import parseRooms from './demoParseRooms.json'
import gens from './demoGen.json'
import { DEMO_PROMPTS } from './demoPrompts'

export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== '0'   // demo branch 預設開，要關設 VITE_DEMO_MODE=0
export const demoPhoto = ref(false)   // 目前上傳的是範例照片
export const DEMO_PHOTO_PATH = 'demo/living_room.jpg'

// DEMO 模式下不管上傳哪張平面圖，都直接用預先解析好的結果（不上傳、不辨識）
export const DEMO_PLAN_PATH = 'artifacts/uploads/demo_floorplan.png'
export const isDemoPlan = () => DEMO_MODE
export const demoPlan = ref(false)

// demo-modern.jpg → { modern: url }；original 是換風格前的原照片
const IMAGES = Object.fromEntries(
  Object.entries(import.meta.glob('@/assets/home/demo-*.jpg', { eager: true, import: 'default' }))
    .map(([p, url]) => [p.match(/demo-(\w+)\.jpg/)[1], url]),
)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const json = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })

// 沒命中回 null，呼叫端照常打後端
export async function demoIntercept(path, data) {
  if (demoPlan.value && path === '/api/detect-rooms') {
    await sleep(3000)
    return json(detectRooms)
  }
  // 點進房間的家具辨識：房型與尺寸對得上錄好的那間就直接回
  if (demoPlan.value && path === '/api/parse-floor-plan') {
    const hit = Object.values(parseRooms).find((r) => r.room_type === data.room_type
      && Math.abs(r.w - data.room_w) < 0.05 && Math.abs(r.d - data.room_d) < 0.05)
    if (hit) {
      await sleep(2000)
      return json(hit.response)
    }
  }
  // 整層逐間生成與批次套用風格（plan 只帶 style_params）：房間（space_id）加範例 prompt 對得上就直接回
  if (demoPlan.value && path === '/api/generate' && !data.plan?.generated_image_path && !data.refine_mode) {
    const p = DEMO_PROMPTS.find((x) => (data.text_prompt || '').includes(x.text))
    const hit = p && gens[`${data.space_id}|${p.id}`]
    if (hit) {
      await sleep(5000)
      return json({ ...hit, generated_image_url: new URL(hit.generated_image_url, location.origin).href })
    }
  }
  if (!demoPhoto.value || path !== '/api/generate') return null
  const id = data.style_profile_id
  // ponytail: 局部修改、移動家具等還沒寫死，先走真後端
  if (!IMAGES[id] || id === 'original' || data.refine_mode || data.mask_image_path) return null
  await sleep(4000)   // 假裝生成中，讓 loading 動畫跑完
  const url = new URL(IMAGES[id], location.origin).href
  return new Response(JSON.stringify({
    status: 'success',
    task_id: `demo-${id}`,
    generated_image_path: url,
    generated_image_url: url,
    style_params: { style_profile_id: id },
    render_result: { generation_params: { seed: 42, backend: 'demo' } },
    elapsed_time: '4.00s',
    timings: {},
    timing_runs: [],
  }), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
