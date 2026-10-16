---
name: door-not-facing-mirror
description: 風水：門不對鏡，鏡面不正對門口
type: fengshui
trigger: door_not_facing_mirror
order: 10
enforce:
  - door_sightline_clear
prompt_addition: "mirror placed off the direct line of sight from the doorway, never mounted facing the entrance"
parameters:
  blocked_types:
    - mirror
  margin: 0.04
  pad: 0.02
---

# Door Not Facing Mirror

「門不對鏡」——一進門就被鏡面正對回照，傳統上視為把進門的氣直接反射出去。

## When to Apply

`special_constraints.door_not_facing_mirror` 為 `true` 時觸發。
房間裡沒有 `mirror` 型別的家具時自動無作用。

## Enforcement

與 `door-not-facing-stove`／`door-not-facing-toilet` 共用 `door_sightline_clear`，
只是 `blocked_types` 換成 `mirror`：鏡子不得落在門的正向視線帶上，重疊就沿橫向推開。

## Notes

這條規則排在 `mirror-not-facing-bed` 之前（order 10 < 12），先把鏡子挪到定位，
再用鏡子的最終位置去判斷床有沒有被照到——反過來排會拿舊位置做判斷。

別名表已收錄 wall_mirror / full_length_mirror / dressing_mirror /
floor_mirror / looking_glass / vanity_mirror。
