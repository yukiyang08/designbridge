#!/bin/bash
# 換風格實驗：每一題跑「FLUX 基準（家電保護開）→ Gemini flash → Gemini＋FLUX LoRA 接力」。
# 用法（專案根目錄）：scripts/restyle_ab/run_cases.sh <cases.txt> <輸出資料夾>
# cases.txt 每行：<題號> <照片路徑（artifacts/ 底下，用 / 分隔）> <style_id> <風格中文名>
set -u
CASES="$1"; OUT="$2"; HERE="$(dirname "$0")"
mkdir -p "$OUT"
export DESIGNBRIDGE_PHOTO_RESTYLE_PROTECT_FIXTURES=true PYTHONUTF8=1
# read -r：路徑裡的反斜線不能被吃掉（第一輪就是這樣整批失敗）
while read -r cid photo sid zh; do
  [ -z "$cid" ] && continue
  python -u "$HERE/baseline.py" "$sid" "$zh" "$photo" > "$OUT/base_$cid.log" 2>&1
  if ! grep -q '"backend": "photo_restyle_fal"' "$OUT/base_$cid.log"; then echo "$cid 基準失敗，見 $OUT/base_$cid.log"; continue; fi
  python -u "$HERE/gemini_edit.py" "$photo" "$OUT/base_$cid.log" "$OUT/$cid" | tail -1
  [ -f "$OUT/$cid/gemini-3.1-flash-image.png" ] && python -u "$HERE/hybrid.py" "$OUT/$cid/gemini-3.1-flash-image.png" "$OUT/base_$cid.log" "$OUT/$cid" 0.25 | tail -1
  echo "$cid done"
done < "$CASES"
