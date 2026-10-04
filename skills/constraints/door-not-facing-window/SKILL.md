---
name: door-not-facing-window
description: 風水：穿堂煞，門直通對牆的窗，中間要有屏風擋氣
type: fengshui
trigger: door_not_facing_window
order: 17
enforce:
  - door_window_screen
prompt_addition: "a screen, console or tall cabinet placed between the entrance and the window opposite it, so the doorway does not look straight through to the glazing"
parameters:
  blocker_types:
    - bookshelf
    - shelf
    - cabinet
    - wardrobe
    - dresser
    - tv_unit
    - sofa
    - plant
  margin: 0.03
  distance_from_door: 0.22
  pad: 0.02
---

# Door Not Facing Window

「穿堂煞」——門正對著對牆的窗，一進門氣就直穿出去。
傳統解法不是移門移窗（動不了），而是在中間立一道屏風把直線打斷。

## When to Apply

`special_constraints.door_not_facing_window` 為 `true` 時觸發。

## Enforcement

1. 找**直通帶**：門與開在對牆的窗，兩者在同一軸上的投影有交集才算成一線。
2. 帶上已經有 `blocker_types` 的家具擋著就不動——要的是「氣不直穿」，
   不是非得某一件家具站在那個位置。
3. 都沒有時，挑一件 `blocker_types` 的家具搬到帶上、離門 `distance_from_door` 處，
   當成屏風。

## Notes

房間裡一件 `blocker_types` 的家具都沒有時，這條規則無從施力：
保持原樣，verifier 回報滿足（與「沒有爐灶時開門不見灶自動成立」同一套處理）。
提示文字仍會進 prompt，渲染時 LLM 可以自己補一道屏風。

屏風落位之後 `layout_agent` 還會再跑一次 `_push_apart`，若與別的家具打架會被推開，
此時 verifier 會如實回報未滿足，而不是假裝擋住了。
