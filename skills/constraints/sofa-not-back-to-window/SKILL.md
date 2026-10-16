---
name: sofa-not-back-to-window
description: 風水：沙發背後有靠，不背對窗戶
type: fengshui
trigger: sofa_not_back_to_window
order: 14
enforce:
  - not_backed_by_opening
prompt_addition: "sofa backed by a solid wall rather than a window, no seating with its back to the glazing"
parameters:
  types:
    - sofa
    - loveseat
  opening_kind: window
  margin: 0.02
  wall_threshold: 0.12
  pad: 0.02
---

# Sofa Not Back To Window

「沙發背後要有靠山」——背後是窗就是無靠。

## When to Apply

`special_constraints.sofa_not_back_to_window` 為 `true` 時觸發。

## Enforcement

與 `bed-head-not-under-window` 共用 `not_backed_by_opening`，只是 `types` 換成
沙發：沙發貼的那面牆若開著窗且與沙發重疊，就沿牆滑到實牆段。

## Notes

與 `sofa-not-back-to-door`（沙發不背門）互補、可同時啟用：
那條管門、這條管窗，各自只看自己的開口類型。
