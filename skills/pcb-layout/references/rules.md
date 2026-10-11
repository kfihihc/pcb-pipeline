# 设计规则：工程设置与 .kicad_dru

## 三层规则

1. **工程设置**（`.kicad_pro` → board.design_settings.rules）：全板下限，包括线宽、间距、过孔、孔距、板边距。由 `layout/board.toml [rules]` 写入，布线器能读到。
2. **网络类**（`.kicad_pro` → net_settings）：每类的线宽、间距、过孔，用 patterns 匹配网络名。由 `[[netclass]]` 写入，布线器能读到非 Default 的网络类。注意网络类间距对焊盘之间也生效，会和细间距封装冲突。
3. **自定义规则**（`<板>.kicad_dru`）：条件规则，只有 KiCad 的 DRC 认。门禁 rules 检查会用哨兵确认文件已经加载。

## .kicad_dru 写法要点（KiCad 10）

```lisp
(version 1)
(rule "VBUS to other copper"                       ; 名字会出现在 DRC 报告里，写清意图
  (condition "A.NetName == 'VBUS' && B.NetName != 'VBUS' && !(A.Type == 'Pad' && B.Type == 'Pad')")
  (constraint clearance (min 0.3mm)))
(rule "RF to pour clearance"                       ; S3
  (condition "A.NetClass == 'RF' && B.Type == 'Zone'")
  (constraint clearance (min 0.25mm)))
(rule "Single thermal spoke allowed"               ; S3：注意写法是 1，不是 (min 1)
  (condition "A.Type == 'Pad'")
  (constraint min_resolved_spokes 1))
(rule "Antenna area: RF feed only"                 ; S3：禁布区按名字引用
  (condition "A.intersectsArea('Antenna keepout') && A.NetClass != 'RF' && (A.Type == 'Track' || A.Type == 'Via')")
  (constraint disallow track via))
```

- **一处错，整份失效**：`(constraint min_resolved_spokes (min 1))` 这类约束写法错误，或者括号不配对，都会让 KiCad 10 静默丢弃整个文件：DRC 0 违规、退出码 0、没有任何提示（2026-10-09 实测）。门禁的哨兵检查能发现这种情况。改完规则后，在 KiCad 的 Board Setup → Custom Rules 里点 “Check rule syntax” 也能看到报错。
- **不要和封装冲突**：厂家焊盘之间的间距由封装决定。规则要排除焊盘对焊盘（`!(A.Type == 'Pad' && B.Type == 'Pad')`），或者用 `A.memberOfFootprint('J1')` 这类条件把那个封装排除掉。
- **测试规则**：在副本里故意造一处违规（比如把一段 VBUS 走线挪近别的网络），确认 DRC 报出的规则名就是你写的那条。哨兵只能证明文件加载了，不能证明某条规则的条件写对了。
- **布线器看不到**：要让布线器遵守的约束，同时写成禁布区或网络类，或者在 `layout/route.toml` 的 `net_clearances` 里镜像一份。

## 禁布区（layout/board.toml [[keepout]]）

```toml
[[keepout]]
name = "J1 shell"            # 名字可以在 .kicad_dru 里用 intersectsArea('J1 shell') 引用
rect = [0.0, 3.5, 5.3, 14.5] # 板框坐标（mm），或者 around = "J1" 加 margin（按庭院）
layers = ["F.Cu"]
no_tracks = true
no_vias = true               # 另有 no_pours、no_pads、no_footprints
```

常见用法：

- 金属外壳下方（连接器、屏蔽罩、晶振金属壳）；
- 天线净空区；
- 安装孔周围；
- 板边的连接器插拔区；
- 高压隔离槽。
