---
name: stove-not-under-window
description: 風水：灶後不宜空，爐灶不背窗
type: fengshui
trigger: stove_not_under_window
order: 15
enforce:
  - not_backed_by_opening
prompt_addition: "cooktop backed by a solid wall, not placed under or against a window"
parameters:
  types:
    - stove
  opening_kind: window
  margin: 0.02
  wall_threshold: 0.12
  pad: 0.02
---

# Stove Not Under Window

「灶後不宜空」——爐灶背後要是實牆，背著窗等於背後無依。
實務上也是安全考量：窗邊的風會吹熄爐火、吹動窗簾。

## When to Apply

`special_constraints.stove_not_under_window` 為 `true` 時觸發。
房間裡沒有 `stove` 時自動無作用。

## Enforcement

共用 `not_backed_by_opening`：爐灶貼的那面牆若開著窗且與爐灶重疊，
沿牆滑到實牆段，推去離原位較近的一側。
