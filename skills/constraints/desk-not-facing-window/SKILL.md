---
name: desk-not-facing-window
description: 風水：書桌不正對窗，側對窗戶獲得自然側光而非直射眩光
type: fengshui
trigger: desk_not_facing_window
order: 6
label: 書桌不正對窗
category: reflect
severity: 1
rooms: [study, bedroom, kids_room]
requires:
- [desk]
needs: [window]
reason: 正對窗戶會有眩光，眼睛容易疲勞；側對窗戶的側光最適合閱讀。
remedy: 加百葉窗或紗簾柔化光線。
enforce:
  - desk_not_facing_window
prompt_addition: "desk placed with its side to the window rather than directly facing it, good natural side-light without glare"
parameters:
  push: 0.15
  min_y: 0.22
  window_wall_threshold: 0.15
  desk_threshold: 0.20
---

# Desk Not Facing Window

若書桌正對頂牆窗戶（中心線對齊），向內推移 `push`，確保最終 `y ≥ min_y`。

## When to Apply

`special_constraints.desk_not_facing_window` 為 `true` 時觸發。

## Enforcement

偵測條件：窗在頂牆（`wy < window_wall_threshold`）、書桌靠近頂牆（`y < desk_threshold`）、水平中心線重疊。
滿足則推移 `push`，下限取 `min_y`。
