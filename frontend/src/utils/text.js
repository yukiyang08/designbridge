// Gemini 產生的中文描述常以「這是一個/這是一間…」開頭（提示詞本身沒這樣要求，
// 但模型不總是照做）；顯示時去掉這個贅詞開頭，不改資料庫/後端回傳的原始內容。
export function cleanDescription(text) {
  if (typeof text !== 'string') return ''
  return text.replace(/^這是一?(個|間|幅|處)\s*/, '')
}
