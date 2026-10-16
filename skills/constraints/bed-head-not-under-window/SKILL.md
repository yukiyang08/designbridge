---
name: bed-head-not-under-window
description: 風水：床頭靠實牆，不睡在窗戶底下
type: fengshui
trigger: bed_head_not_under_window
order: 13
enforce:
  - not_backed_by_opening
prompt_addition: "bed headboard against a solid wall, never under or against a window"
parameters:
  types:
    - bed
    - bunk_bed
  opening_kind: window
  margin: 0.02
  wall_threshold: 0.12
  pad: 0.02
---

# Bed Head Not Under Window

「床頭要有靠」——床頭那面牆必須是實牆，不能是窗。
除了風水，實務上也是為了擋冷風與噪音。

## When to Apply

`special_constraints.bed_head_not_under_window` 為 `true` 時觸發。

## Enforcement

1. 床貼哪面牆（四邊離牆最近的那一邊），床頭就在那面牆。
2. 只看開在**同一面牆**上的窗；其他牆的窗與床頭無關。
3. 窗在牆上佔的區間往兩側各加 `margin` 成為禁帶，床沿著牆滑出帶外，
   推去離原位較近的一側。

## Notes

只處理已經貼牆（距牆 ≤ `wall_threshold`）的床。擺在房間中央的床沒有「床頭靠牆」
可言，這條規則不對它出手，以免把一張刻意置中的床硬拉到牆邊。

牆上的窗寬到床兩側都放不下時保持原位，由 verifier 如實回報未滿足。
