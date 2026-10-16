---
name: stove-away-from-water
description: 風水：水火不相容，爐灶與水槽、冰箱保持距離
type: fengshui
trigger: stove_away_from_water
order: 16
enforce:
  - group_separation
prompt_addition: "cooktop kept well clear of the sink and refrigerator, with worktop separating the hot and wet zones"
parameters:
  group_a:
    - stove
  group_b:
    - sink
    - fridge
  min_gap: 0.12
  iterations: 30
  pad: 0.02
---

# Stove Away From Water

「水火不相容」——爐灶（火）與水槽、冰箱（水）不宜緊鄰。
實務上這也正是廚房三角動線要留出備料檯面的理由。

## When to Apply

`special_constraints.stove_away_from_water` 為 `true` 時觸發。
房間裡缺少任一邊（沒爐灶、或沒水槽也沒冰箱）時自動無作用。

## Enforcement

迭代推開**跨組**的配對，直到每對間距 ≥ `min_gap`（5 m 房間約 60 cm）。
組內的配對不動——兩座爐灶之間怎麼排不是這條規則管的事。

## Notes

`sink` / `fridge` 需要在 `FURNITURE_SIZES` 的受控詞彙裡，否則 LLM 給的
`kitchen_sink` / `refrigerator` 等自由標籤會被收斂成 `default`，這條規則不會觸發。
別名表已收錄 kitchen_sink / washbasin / wash_basin / basin / washstand /
mop_sink、refrigerator / freezer / icebox / fridge_freezer。
