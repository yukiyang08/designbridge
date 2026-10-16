---
name: door-not-facing-stove
description: 風水：開門不見灶，爐灶不正對門口
type: fengshui
trigger: door_not_facing_stove
order: 8
enforce:
  - door_sightline_clear
prompt_addition: "kitchen stove placed out of the direct line of sight from the doorway, not visible straight through the entrance"
parameters:
  blocked_types:
    - stove
  margin: 0.04
  pad: 0.02
---

# Door Not Facing Stove

「開門不見灶」——站在門口直視前方不應該看到爐灶。

## When to Apply

`special_constraints.door_not_facing_stove` 為 `true` 時觸發。
房間裡沒有 `stove` 型別的家具時自動無作用。

## Enforcement

門寬往室內延伸出一條**視線帶**（兩側各加 `margin`）。爐灶的 footprint 與這條帶重疊
就是「見灶」，沿橫向把它推出帶外，推去離原位較近的一側。

上下牆的門，帶子沿 y 延伸、橫跨 x（爐灶左右移）；左右牆的門則相反。

## Notes

`stove` 需要在 `FURNITURE_SIZES` 的受控詞彙裡，否則 LLM 給的
`cooktop` / `gas_stove` 等自由標籤會被收斂成 `default`，這條規則就永遠不會觸發。
別名表已收錄 cooktop / stovetop / hob / gas_stove / range / cooker / oven。
