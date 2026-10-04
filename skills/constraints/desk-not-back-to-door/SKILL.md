---
name: desk-not-back-to-door
description: 風水：書桌座位不背對門口，坐時能側身見門
type: fengshui
trigger: desk_not_back_to_door
order: 7
enforce:
  - desk_not_back_to_door
prompt_addition: "desk positioned so the seated person is not with their back to the doorway, able to see the entrance from the chair"
parameters:
  desk_types:
    - desk
  margin: 0.03
  pad: 0.02
---

# Desk Not Back To Door

書桌靠哪面牆，坐著的人就面向那面牆，背因此朝向**對牆**。
若門正好開在那面對牆、而且落在書桌的橫向範圍內，就是「背門」。

## When to Apply

`special_constraints.desk_not_back_to_door` 為 `true` 時觸發。

## Enforcement

1. 取書桌四邊離牆最近的那一邊當作靠牆面，其對牆即為「背後」那面牆。
2. 只檢查開在該對牆上的門（`_opening_wall`），其餘方位的門與這條規則無關。
3. 門寬往室內延伸成一條視線帶（左右加 `margin`）；書桌橫向範圍與帶子重疊即違規。
4. 沿牆推開書桌，推去離原位較近的一側，讓座位側身見門而非背門。

## Notes

與 `desk-not-facing-window`（書桌不背窗）是兩條獨立規則，可同時啟用：
前者管窗、這條管門，各自只處理自己的開口類型。

房間窄到書桌兩側都塞不下時保持原位，由 verifier 如實回報未滿足——
把書桌推進牆裡只會製造假的合規。
