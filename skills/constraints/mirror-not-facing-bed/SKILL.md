---
name: mirror-not-facing-bed
description: 風水：鏡不照床，鏡面不正對睡床
type: fengshui
trigger: mirror_not_facing_bed
order: 12
enforce:
  - item_sightline_clear
prompt_addition: "mirror positioned so it does not reflect the bed, mounted on a wall out of the bed's line of sight"
parameters:
  source_types:
    - mirror
  blocked_types:
    - bed
    - bunk_bed
  margin: 0.04
  pad: 0.02
---

# Mirror Not Facing Bed

「鏡不照床」——睡醒時不應該在鏡子裡看見自己。

## When to Apply

`special_constraints.mirror_not_facing_bed` 為 `true` 時觸發。
房間裡沒有 `mirror`（或沒有床）時自動無作用。

## Enforcement

鏡子貼哪面牆就背著那面牆，鏡面朝向室內——形狀與門的視線帶完全相同，
只是起點從門換成鏡子（`item_sightline_clear` / `_item_facing_band`）。
床落在這條帶上就沿橫向推開。

## Notes

移動的是**床**而不是鏡子：鏡子是掛在牆上的，換牆等於換裝潢，
把床挪開半公尺才是真正會採用的解法。要挪鏡子請改勾 `door-not-facing-mirror`。
