---
name: door-not-facing-toilet
description: 風水：開門不見廁所，馬桶不正對門口
type: fengshui
trigger: door_not_facing_toilet
order: 9
enforce:
  - door_sightline_clear
prompt_addition: "toilet placed out of the direct line of sight from the doorway, screened from the entrance"
parameters:
  blocked_types:
    - toilet
  margin: 0.04
  pad: 0.02
---

# Door Not Facing Toilet

「開門不見廁所」——站在門口直視前方不應該看到馬桶。

## When to Apply

`special_constraints.door_not_facing_toilet` 為 `true` 時觸發。
房間裡沒有 `toilet` 型別的家具時自動無作用。

## Enforcement

與 `door-not-facing-stove` 共用 `door_sightline_clear` 這支檢查函式，
只是 `blocked_types` 換成 `toilet`——兩條規則的幾何判斷本來就是同一件事：
標的不得落在門的正向視線帶上。

## Notes

本規則在**單一房間**的座標系內處理，也就是衛浴本身那道門與馬桶的關係。
整戶尺度的「大門正對廁所門」需要跨房間的平面資訊，目前的單房規劃模型還涵蓋不到。

別名表已收錄 wc / water_closet / commode / lavatory。
