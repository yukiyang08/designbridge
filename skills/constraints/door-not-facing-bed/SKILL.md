---
name: door-not-facing-bed
description: 風水：開門不見床，床不落在門口的正向視線上
type: fengshui
trigger: door_not_facing_bed
order: 11
label: 開門不見床
category: door
severity: 2
rooms: [bedroom, kids_room]
requires:
- [bed, bunk_bed]
needs: [door]
reason: 站在門口就看見整張床，私密性差；開門時床也直接暴露在外。
remedy: 在門與床之間放衣櫃、屏風，或掛門簾擋住視線。
enforce:
  - door_sightline_clear
prompt_addition: "bed placed out of the direct line of sight from the bedroom door, not visible straight through the entrance"
parameters:
  blocked_types:
    - bed
    - bunk_bed
  margin: 0.04
  pad: 0.02
---

# Door Not Facing Bed

「開門不見床」——站在門口直視前方不應該整張床映入眼簾。

## When to Apply

`special_constraints.door_not_facing_bed` 為 `true` 時觸發。
房間裡沒有 `bed` / `bunk_bed` 時自動無作用。

## Enforcement

共用 `door_sightline_clear`：床的 footprint 與門的正向視線帶重疊就沿橫向推開，
推去離原位較近的一側。
