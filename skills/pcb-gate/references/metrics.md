# checks/metrics.toml：声明式指标

每个 `[[metric]]` 包含：

- `id`：唯一；
- `kind` 及其参数；
- 至多一个判据：`eq`、`min`、`max`、`approx`+`tol`、`keys_subset`、`each_max`、`each_min`；
- `why`：必填，写需求编号、数据手册页码或变更单。

没有判据的指标只记录数值，出现在 `reports/metrics.json` 里，方便版本对比。

| kind | 参数 | 返回值 | 典型用途 |
| --- | --- | --- | --- |
| tracks_on_layer | layer | 段数 | 地平面层不许走线：`eq = 0` |
| track_count | [layer] [net] | 段数 | 统计 |
| via_count | [net] | 个数 | 统计 |
| net_length_mm | net 或 nets | mm（nets 时返回字典） | USB、射频、时钟线长：`max` |
| net_vias | net 或 nets | 个数 | 敏感网络的换层次数：`max` |
| net_layers | net 或 nets | 层名列表 | 射频只在表层：`eq = ["F.Cu"]` |
| min_track_width_mm | net 或 nets，[ignore_shorter_mm] | mm | 电源和开关节点线宽：`min`；颈缩用 `ignore_shorter_mm` 忽略 |
| pad_distance_mm | a = "U1.1", b = "C9.2" | mm | 匹配器件紧贴引脚 |
| decoupling_mm | pin = "U1.2", cap = "C1" | mm（到电容的同网焊盘） | 去耦距离：`max` |
| vias_in_pad | pad = "U1.57" | 个数（焊盘内的同网过孔，加上封装自带的金属化孔） | 散热焊盘过孔：`min` |
| via_sizes | — | {"0.6/0.3": n} | 只许用规定的规格：`keys_subset` |
| items_in_area | area（禁布区名），allow_nets | 个数 | 天线净空内只许出现射频馈线：`eq = 0` |
| footprint_sides | — | {"F": n, "B": m} | 单面贴装：`eq = {F = 9, B = 0}` |
| zone_area_mm2 | net, layer | mm² | 铺铜面积（看趋势） |
| zone_islands | net, layer | 块数 | 平面没被切碎：`eq = 1` |
| length_skew_mm | nets = [p, n] | mm | 差分对长度差：`max` |
| moved_from | anchors（JSON 文件），tolerance_mm，[origin] | {ref: 距离} | 复刻工程与原板位置的偏差：`keys_subset` |
| script | path，[function]，key（点号路径） | 任意 | 声明式写不出来的项目检查 |

判据：

- `eq`：完全相等（数值、列表、字典都可以）；
- `approx` + `tol`：浮点近似；
- `min` / `max`：数值上下限，值为 None（例如网络上没有走线）时判失败；
- `keys_subset`：字典里不能出现名单外的键（比如偏离位置的器件不许增加）；
- `each_max` / `each_min`：对字典的每个键单独给限值，可以带 `tol`。值是列表时取最后一个元素，兼容 S3 的 [原图值, 新值] 格式。

示例（S3 的部分规则，声明式写法）：

```toml
[[metric]]
id = "in1_tracks"
kind = "tracks_on_layer"
layer = "In1.Cu"
eq = 0
why = "In1 是完整 GND 平面"

[[metric]]
id = "rf_layers"
kind = "net_layers"
nets = ["RF_ANT", "LNA_IN", "RF_SHUNT"]
why = "RF 链只在表层（实测记录）"

[[metric]]
id = "antenna_clear"
kind = "items_in_area"
area = "Antenna keepout"
allow_nets = ["RF_ANT", "LNA_IN", "RF_SHUNT"]
eq = 0
why = "天线净空区只允许 RF 馈线"

[[metric]]
id = "gnd_in1_single"
kind = "zone_islands"
net = "GND"
layer = "In1.Cu"
eq = 1
why = "In1 地平面不能被切碎"
```

对比实测：在 S3 上，声明式指标算出的 RF 链长、C9 到 U1 第 1 脚的距离、散热焊盘过孔数、最小线宽、去耦距离、USB 长度和过孔数、过孔规格，与 S3 自己的 `gen/check_v02.py` 结果一致（2026-10-10）。
