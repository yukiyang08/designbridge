---
name: door-not-facing-bed
description: 風水：開門不見床，床不落在門口的正向視線上
type: fengshui
trigger: door_not_facing_bed
order: 11
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

## Notes

與 `bed-not-facing-door`（床腳不對門）是兩條**不同強度**的規則，可以只挑一條：

- `bed_not_facing_door`：只管床腳端對不對著門，床身在視線帶上不算違規。
- `door_not_facing_bed`：整張床都不得落在視線帶上，較嚴格。

兩條同時勾也不會互相破壞——嚴的那條滿足時，鬆的那條必然也滿足。
