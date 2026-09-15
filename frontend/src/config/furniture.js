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
  // 浴室／兒童房（Figma 有這兩個房型）。後端 FURNITURE_SIZES 沒收錄這些 type，
  // 會落到 default 尺寸，但名稱仍會進 prompt，渲染時看得出來。
  bathtub: '浴缸', shower: '淋浴間', toilet: '馬桶', sink: '洗手台',
  vanity: '浴櫃', towel_rack: '毛巾架',
  toy_storage: '玩具收納', study_chair: '兒童椅', bean_bag: '懶骨頭',
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
  bathtub: 'mdi:bathtub-outline', shower: 'mdi:shower', toilet: 'mdi:toilet',
  sink: 'mdi:sink', vanity: 'mdi:cupboard-outline', towel_rack: 'mdi:hanger',
  toy_storage: 'mdi:toy-brick-outline', study_chair: 'mdi:seat-outline',
  bean_bag: 'mdi:sofa-single-outline',
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
    { value: 'lamp',          label: '燈' },
  ],
  kitchen: [
    { value: 'cabinet',       label: '廚櫃' },
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
  toy_storage: [0.14, 0.08], study_chair: [0.07, 0.07], bean_bag: [0.11, 0.11],
  default: [0.12, 0.10],
}

export function furnitureDefaultSize(type) {
  return FURNITURE_DEFAULT_SIZE[type] || FURNITURE_DEFAULT_SIZE.default
}
