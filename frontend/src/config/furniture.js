// 家具 type → 中文標籤，2D（LayoutEditor）跟 3D（LayoutPreview3D）共用同一份，
// 避免兩邊各自維護一份清單、字彙表不同步（後端字彙表見 layout_agent.py 的
// FURNITURE_SIZES / scene_graph_to_depth.py 的 FURNITURE_HEIGHTS）。
export const FURNITURE_LABEL_ZH = {
  sofa: '沙發', loveseat: '雙人沙發', armchair: '扶手椅', chair: '椅子',
  coffee_table: '茶几', dining_table: '餐桌', desk: '書桌', nightstand: '床頭櫃',
  tv_unit: '電視櫃', tv: '電視',
  bed: '床', bunk_bed: '上下舖', bunk_ladder: '爬梯',
  wardrobe: '衣櫃', bookshelf: '書櫃', shelf: '層架',
  cabinet: '櫃子', dresser: '梳妝台',
  lamp: '立燈', plant: '盆栽', rug: '地毯',
  cat_tree: '貓跳台', dog_bed: '狗窩', litter_box: '貓砂盆',
  // 風水規則的標的：沒有這幾件家具，開門不見灶／水火不相容／鏡不照床就永遠不會觸發，
  // 所以它們同時進了後端的 FURNITURE_SIZES 與這裡的選單。
  stove: '爐灶', fridge: '冰箱', mirror: '鏡子',
  // 浴室／兒童房（Figma 有這兩個房型）。後端 FURNITURE_SIZES 沒收錄這些 type，
  // 會落到 default 尺寸，但名稱仍會進 prompt，渲染時看得出來。
  bathtub: '浴缸', shower: '淋浴間', toilet: '馬桶', sink: '洗手台',
  vanity: '浴櫃', towel_rack: '毛巾架',
  toy_storage: '玩具收納', study_chair: '兒童椅', bean_bag: '懶骨頭',
  // 陽台（CAD 房型生成會產生這個房型，見 designbridge/roomplan）。
  washer: '洗衣機', drying_rack: '曬衣架', balcony_cabinet: '陽台收納櫃', mop_sink: '洗衣槽',
  default: '家具',
}

// type 不在表裡時的保底：底線換空格的英文原字（至少不是空白），呼叫端可再自行覆蓋。
export function furnitureLabel(type) {
  return FURNITURE_LABEL_ZH[type] || String(type || '').replace(/_/g, ' ')
}

// Iconify 圖示名稱（mdi 集合），FURNITURE_ICON_MAP 供 <Icon :icon="..."/> 使用。
// 沒有精準對應圖示的類型（邊几、床頭櫃、層架、狗窩…），用語意最接近的湊。
export const FURNITURE_ICON_MAP = {
  sofa: 'mdi:sofa', loveseat: 'mdi:sofa-outline', armchair: 'mdi:sofa-single', chair: 'mdi:seat',
  coffee_table: 'mdi:table-furniture', dining_table: 'mdi:table-chair', desk: 'mdi:desk',
  side_table: 'mdi:table-furniture', nightstand: 'mdi:table-furniture',
  tv_unit: 'mdi:television', tv: 'mdi:television',
  bed: 'mdi:bed', bunk_bed: 'mdi:bunk-bed', bunk_ladder: 'mdi:ladder',
  wardrobe: 'mdi:wardrobe', bookshelf: 'mdi:bookshelf', shelf: 'mdi:bookshelf',
  cabinet: 'mdi:cupboard', dresser: 'mdi:dresser',
  lamp: 'mdi:floor-lamp', plant: 'mdi:flower', rug: 'mdi:rug',
  cat_tree: 'mdi:cat', dog_bed: 'mdi:dog', litter_box: 'mdi:tray-full',
  stove: 'mdi:stove', fridge: 'mdi:fridge', mirror: 'mdi:mirror',
  bathtub: 'mdi:bathtub-outline', shower: 'mdi:shower', toilet: 'mdi:toilet',
  sink: 'mdi:sink', vanity: 'mdi:cupboard-outline', towel_rack: 'mdi:hanger',
  toy_storage: 'mdi:toy-brick-outline', study_chair: 'mdi:seat-outline',
  bean_bag: 'mdi:sofa-single-outline',
  washer: 'mdi:washing-machine', drying_rack: 'mdi:hanger', balcony_cabinet: 'mdi:cupboard-outline',
  mop_sink: 'mdi:sink',
  default: 'mdi:cube-outline',
}

export function furnitureIcon(type) {
  return FURNITURE_ICON_MAP[type] || FURNITURE_ICON_MAP.default
}

// 房間類型 + 各房型常見家具——SidebarForm（Step 1 選家具）跟 LayoutEditor（2D 編輯器的
// 家具面板）共用同一份，兩邊選單才不會慢慢長歪。
// 只留佈局引擎有完整家具尺寸支援的四個房型（見 layout_agent.py 的 FURNITURE_SIZES）。
// 浴室／兒童房／餐廳的家具清單留在下面的 FURNITURE_BY_ROOM，要放回選單只要
// 把對應項目加回這個陣列；使用者也隨時可以用「＋ 自訂」打任意房型。
export const ROOM_OPTIONS = [
  { value: 'living_room', label: '客廳' },
  { value: 'bedroom',     label: '臥室' },
  { value: 'kitchen',     label: '廚房' },
  { value: 'study',       label: '書房' },
]

// 空間類型卡片用的大圖示；自訂房型沒有對應就用 roomIcon() 的預設
const ROOM_ICONS = {
  dining: 'mdi:silverware-fork-knife', living_room: 'mdi:sofa', bedroom: 'mdi:bed-king', kitchen: 'mdi:stove', study: 'mdi:desk',
}
import livingRoomPhoto from '@/assets/rooms/living_room.jpg'
import bedroomPhoto from '@/assets/rooms/bedroom.jpg'
import kitchenPhoto from '@/assets/rooms/kitchen.jpg'
import studyPhoto from '@/assets/rooms/study.jpg'
import livingDiningPhoto from '@/assets/rooms/living_dining.jpg'
import bathroomPhoto from '@/assets/rooms/bathroom.jpg'
import balconyPhoto from '@/assets/rooms/balcony.jpg'
import diningPhoto from '@/assets/rooms/dining.jpg'

// 空間類型卡片的實景照；自訂房型沒有照片，卡片退回圖示
const ROOM_PHOTOS = {
  living_room: livingRoomPhoto, bedroom: bedroomPhoto, kitchen: kitchenPhoto, study: studyPhoto,
  living_dining: livingDiningPhoto, bathroom: bathroomPhoto, balcony: balconyPhoto, dining: diningPhoto,
}
export const roomPhoto = (value) => ROOM_PHOTOS[value] || ''
export const roomIcon = (value) => ROOM_ICONS[value] || 'mdi:home-variant-outline'

export const FURNITURE_BY_ROOM = {
  living_room: [
    { value: 'sofa',          label: '沙發' },
    { value: 'coffee_table',  label: '茶几' },
    { value: 'tv_unit',       label: '電視櫃' },
    { value: 'armchair',      label: '扶手椅' },
    { value: 'rug',           label: '地毯' },
    { value: 'plant',         label: '植物' },
    { value: 'bookshelf',     label: '書架' },
    { value: 'side_table',    label: '邊桌' },
  ],
  bedroom: [
    { value: 'bed',           label: '床' },
    { value: 'wardrobe',      label: '衣櫃' },
    { value: 'nightstand',    label: '床頭柜' },
    { value: 'desk',          label: '書桌' },
    { value: 'dresser',       label: '梳妝台' },
    { value: 'armchair',      label: '扶手椅' },
    { value: 'mirror',        label: '鏡子' },
    { value: 'lamp',          label: '燈' },
  ],
  kitchen: [
    { value: 'cabinet',       label: '廚櫃' },
    { value: 'stove',         label: '爐灶' },
    { value: 'sink',          label: '水槽' },
    { value: 'fridge',        label: '冰箱' },
    { value: 'shelf',         label: '層架' },
  ],
  dining_room: [
    { value: 'dining_table',  label: '餐桌' },
    { value: 'chair',         label: '餐椅' },
    { value: 'cabinet',       label: '餐櫃' },
    { value: 'shelf',         label: '層架' },
  ],
  study: [
    { value: 'desk',          label: '書桌' },
    { value: 'chair',         label: '椅子' },
    { value: 'bookshelf',     label: '書架' },
    { value: 'armchair',      label: '扶手椅' },
    { value: 'side_table',    label: '邊桌' },
    { value: 'lamp',          label: '燈' },
  ],
  bathroom: [
    { value: 'bathtub',       label: '浴缸' },
    { value: 'shower',        label: '淋浴間' },
    { value: 'toilet',        label: '馬桶' },
    { value: 'sink',          label: '洗手台' },
    { value: 'vanity',        label: '浴櫃' },
    { value: 'mirror',        label: '鏡子' },
    { value: 'towel_rack',    label: '毛巾架' },
    { value: 'shelf',         label: '層架' },
  ],
  kids_room: [
    { value: 'bed',           label: '兒童床' },
    { value: 'bunk_bed',      label: '上下舖' },
    { value: 'desk',          label: '書桌' },
    { value: 'study_chair',   label: '兒童椅' },
    { value: 'wardrobe',      label: '衣櫃' },
    { value: 'bookshelf',     label: '書架' },
    { value: 'toy_storage',   label: '玩具收納' },
    { value: 'bean_bag',      label: '懶骨頭' },
    { value: 'rug',           label: '地毯' },
  ],
  // 客餐廳合一——CAD 房型生成（designbridge/roomplan）把客廳跟餐廳算成同一間房，
  // 家具面板就把兩邊清單合併，不用另外拆房間。
  living_dining: [
    { value: 'sofa',          label: '沙發' },
    { value: 'coffee_table',  label: '茶几' },
    { value: 'tv_unit',       label: '電視櫃' },
    { value: 'dining_table',  label: '餐桌' },
    { value: 'chair',         label: '餐椅' },
    { value: 'armchair',      label: '扶手椅' },
    { value: 'rug',           label: '地毯' },
    { value: 'plant',         label: '植物' },
    { value: 'bookshelf',     label: '書架' },
    { value: 'side_table',    label: '邊桌' },
  ],
  // 陽台——CAD 房型生成會產生這個房型，舊版精靈原本沒有對應的家具面板。
  balcony: [
    { value: 'washer',          label: '洗衣機' },
    { value: 'drying_rack',     label: '曬衣架' },
    { value: 'balcony_cabinet', label: '收納櫃' },
    { value: 'mop_sink',        label: '洗衣槽' },
    { value: 'plant',           label: '植物' },
  ],
}

// FURNITURE_BY_ROOM 條目沒有預設尺寸，LayoutEditor 的「新增家具」要落地一個正規化 w/h——
// 沒列在這裡的類型（廚櫃/層架…目前碰不到，但保底一下）就退回 default。
export const FURNITURE_DEFAULT_SIZE = {
  sofa: [0.30, 0.13], armchair: [0.12, 0.12], chair: [0.08, 0.08],
  coffee_table: [0.15, 0.10], side_table: [0.08, 0.08], dining_table: [0.24, 0.18],
  desk: [0.20, 0.10], tv_unit: [0.22, 0.07], bed: [0.30, 0.40],
  nightstand: [0.08, 0.08], wardrobe: [0.20, 0.10], bookshelf: [0.18, 0.08],
  cabinet: [0.15, 0.08], dresser: [0.16, 0.08], shelf: [0.16, 0.06],
  plant: [0.06, 0.06], lamp: [0.05, 0.05], rug: [0.38, 0.24],
  bathtub: [0.30, 0.14], shower: [0.16, 0.16], toilet: [0.09, 0.12],
  sink: [0.10, 0.08], vanity: [0.14, 0.08], towel_rack: [0.08, 0.03],
  stove: [0.13, 0.08], fridge: [0.09, 0.09], mirror: [0.12, 0.03],
  toy_storage: [0.14, 0.08], study_chair: [0.07, 0.07], bean_bag: [0.11, 0.11],
  washer: [0.16, 0.16], drying_rack: [0.20, 0.06], balcony_cabinet: [0.14, 0.08], mop_sink: [0.12, 0.10],
  default: [0.12, 0.10],
}

// 真實尺寸（公尺，寬 × 深）。上面 FURNITURE_DEFAULT_SIZE 是「房間比例」，同一件家具在大房間會
// 變大、小房間變小，跟真實尺寸的門（90cm）、牆放在一起就會顯得不協調；預設擺法一律改用這張表。
export const FURNITURE_REAL_SIZE_M = {
  sofa: [2.0, 0.9], armchair: [0.8, 0.8], chair: [0.45, 0.45],
  coffee_table: [1.0, 0.5], side_table: [0.45, 0.45], dining_table: [1.4, 0.8],
  desk: [1.2, 0.6], tv_unit: [1.6, 0.4], bed: [1.5, 2.0],
  nightstand: [0.45, 0.4], wardrobe: [1.8, 0.6], bookshelf: [0.9, 0.3],
  cabinet: [0.9, 0.5], dresser: [1.0, 0.45], shelf: [0.9, 0.3],
  plant: [0.4, 0.4], lamp: [0.3, 0.3], rug: [2.0, 1.4],
  bathtub: [1.6, 0.75], shower: [0.9, 0.9], toilet: [0.4, 0.7],
  sink: [0.6, 0.45], vanity: [0.8, 0.5], towel_rack: [0.6, 0.15],
  stove: [0.75, 0.5], fridge: [0.7, 0.7], mirror: [0.6, 0.1],
  toy_storage: [0.9, 0.4], study_chair: [0.45, 0.45], bean_bag: [0.7, 0.7],
  washer: [0.6, 0.6], drying_rack: [1.2, 0.4], balcony_cabinet: [0.8, 0.4], mop_sink: [0.5, 0.45],
  default: [0.6, 0.6],
}
export function furnitureRealSize(type) {
  return FURNITURE_REAL_SIZE_M[type] || FURNITURE_REAL_SIZE_M.default
}

// 新增家具用：真實尺寸換成這間房的歸一化 w/h（夾在 [0.04, 0.9]，太小的房間至少看得到、不會比房間大）。
export function furnitureDefaultSize(type, roomW = 5, roomD = 4) {
  const [w, d] = furnitureRealSize(type)
  const c = (v) => Math.max(0.04, Math.min(0.9, v))
  return [c(w / roomW), c(d / roomD)]
}
