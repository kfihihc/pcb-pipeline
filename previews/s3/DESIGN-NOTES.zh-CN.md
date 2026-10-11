# S3 AMOLED 1.75C KiCad 复刻工程（v0.2.1）

从 Waveshare 公开原理图和装配图重建的四层 PCB 工程，保留 ESP32-S3R8、32 MB Flash、AXP2101、CO5300/CST9217 接口、ES8311、ES7210、NS4150B 及原板 GPIO 分配，加入 USB 数据线 ESD 与带充电反接检测的电池保护电路。

这是工程审查版。公开资料只有 PDF、装配图和产品照片，没有原始 PCB、完整厂家 BOM、屏幕排线机械图或可测量实物。因此电气兼容是设计目标，外壳装配、射频和电池故障响应仍须实物验证。板框尺寸由 PDF 比例推算，不宣称已实现毫米级 1:1 机械互换。

> **需要 KiCad 10**（实测 10.0.6）。原理图和 PCB 都是 KiCad 10 格式，KiCad 9 及更早版本打不开，会提示文件来自更新的版本。只有 KiCad 9 时，可以取标签 `v0.2`（KiCad 9.0.2 版），或者直接看 `exports/` 里的原理图 PDF 和各层图。

用 KiCad 10 打开 [s3-amoled-175.kicad_pro](s3-amoled-175.kicad_pro)。工程包含 10 页原理图、202 个器件和项目专用库，标准器件引用 KiCad 自带的库（`${KICAD10_FOOTPRINT_DIR}`）。

## 版本

| 版本 | 位置 | 说明 |
| --- | --- | --- |
| **v0.2.1（当前）** | 本目录 | 迁移到 KiCad 10.0.6。电路、器件位置、走线和过孔不变；同步符号字段，更新系统库封装，并显式划分 GND/AGND 铺铜。详见下文 “v0.2.1：迁移到 KiCad 10” |
| v0.2 | Git 提交 `8713c23`（KiCad 9.0.2） | 按 v0.1 审查意见重做 PCB：恢复原图无源件尺寸与面别、散热焊盘过孔、完整 In1 地平面，重布射频、USB 和开关节点 |
| v0.1 | [`archive/v0.1/`](archive/v0.1/) | 初版，含当时的工程、导出文件和 `validation/` 日志，原样保留 |

| 文件 | 用途 |
| --- | --- |
| `s3-amoled-175.kicad_pro` / `.kicad_sch`（含 9 个分图）/ `.kicad_pcb` | KiCad 工程、原理图、四层 PCB |
| `s3-amoled-175.kicad_dru` | 自定义设计规则（射频间距、天线净空、热焊盘辐条） |
| `bom.csv` / `bom-assembly.csv` | 逐位号清单 / 合并采购清单（含 LCSC 料号、DNP） |
| `exports/` | 原理图 PDF、各层预览、`fabrication-review/` 制造输出、`jlc/` 嘉立创格式 BOM 与坐标 |
| `validation/` | 当前版本的 DRC、ERC、连通性、审查指标，以及 v0.2 各步骤报告 |
| `checks/` | 合并门禁 `run_checks.py`、阈值 `thresholds.json`、版图对比工具 `board_diff.py` |
| CI 工作流（原工程） | 每次推送跑门禁，打版本标签时生成审查包；不包含在浏览副本中 |
| `NOTICE.md` | Apache-2.0 派生与修改声明、第三方库许可 |
| `gen/` | 生成、布线修复、核对与导出脚本 |
| `data/` | 从原厂 PDF 提取的装配位置（`assembly-anchors.json`）、板框（`outline.json`）、原图网表，以及 0201 选料记录。提取脚本在 `gen/pdf/`，其输入还包括调研阶段整理的原板 BOM（`waveshare-bom.csv`） |
| `pyproject.toml` / `uv.lock` | 可选 Python 依赖，由 uv 管理（见“重现方式”） |
| `work/` | 脚本运行时按需创建的临时目录（DSN/SES、修复日志），不入库，可随时删除 |

## 本次交付检查

以系统 KiCad 10.0.6 实测结果为准。没有排除任何 DRC 项，也没有全局关闭 ERC 规则。

| 检查 | 结果 |
| --- | --- |
| PCB DRC（含 `--schematic-parity`） | 0 错误、0 警告、0 未连接、0 原理图差异 |
| 原理图 ERC | 0 错误；2 项警告来自原设计：IMU 辅助总线 SDX/SCX 接 VCC3V3 |
| 引脚 / 封装 / 网表核对 | 202 器件、613 电气引脚全部匹配；24 项 BSP 引脚连接核对通过 |
| 布线 | 4886 段走线（F.Cu 2486、In2.Cu 1057、B.Cu 1343），378 个过孔；In1.Cu 无走线 |
| BOM 与贴片坐标 | 162 个贴装器件一一对应 |
| 合并门禁 `checks/run_checks.py` | 5 项全部通过：ERC、DRC 与原理图一致性、铺铜为最新、30 条审查指标、生成器重跑结果与仓库逐字节一致 |

原始结果见 `validation/drc.json`、`erc.json`、`connectivity.json`，审查指标见 `validation/check-v0.2.json`，汇总见 `validation/summary.json`。这些检查不代表已完成上电、阻抗或机械装配验证。

## v0.2.1：迁移到 KiCad 10

v0.2 用 KiCad 9.0.2 完成。系统升级到 KiCad 10.0.6 后，v0.2 在 KiCad 10 下的 DRC 仍是 0 错误、0 未连接，但还有以下问题，v0.2.1 逐项处理：

| 问题（v0.2 在 KiCad 10 下） | 处理 |
| --- | --- |
| 199 项原理图一致性警告：符号的 `LCSC` 等字段不在封装上（KiCad 10 新增的字段比对） | `gen/sync_fields.py` 把 LCSC、MPN、Review 字段同步到 202 个封装上（隐藏，放在 Fab 层） |
| 6 项 “封装与库不一致”：U1、U2、Q1–Q3、T1 | 逐个比对：焊盘全部相同，差别只在丝印、装配层和庭院线。U2、Q1–Q3、T1（连同未报警的 X1）更新为 KiCad 10 库版本。U1 保留 KiCad 9 版本，固化为 `s3amoled:QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm_ThermalVias`，原因是 KiCad 10 库把 pin 1 丝印三角移到左侧，会被 C9（LNA_IN）焊盘开窗裁掉 |
| 在 KiCad 10 下重铺铜，F/B/In2 的 GND 分别多出 68/71/26 mm²，大部分落在模拟区内：KiCad 10 允许低优先级的 GND 铺进 AGND 未铺到的地方 | GND 铺铜轮廓显式挖去 AGND 区域（`finish_v02.split_ground`）。KiCad 10 重铺后与 v0.2 的铜面积相差：F +0.11、B −0.31、In2 −0.62 mm²。差异在模拟区边界的窄条，以及 v0.2 留在模拟区内的几小块 GND 碎铜 |
| 162 个封装的 3D 模型写作 `${KICAD9_3DMODEL_DIR}`，KiCad 10 不再解析 | 改为 `${KICAD10_3DMODEL_DIR}`；库表改用 `${KICAD10_FOOTPRINT_DIR}`。本机未装 `kicad-packages3d`，3D 视图和 STEP 仍缺模型 |
| 生成器在 KiCad 10 下重跑，输出与仓库不同：网表相同，但符号图形、mcu_rf 页版面和 Tight 封装的装配层随新库变化。`validate.py` 也会重写封装库 | 采纳 KiCad 10 的生成结果，板上 154 个封装随之从项目库更新（焊盘不变）。现在 `build.py`、`validate.py` 重跑与仓库逐字节一致，由门禁检查 |
| 原理图和项目符号库的文件头还是 KiCad 8 的版本号（`20231120`），内容却抄自 KiCad 10 符号库。KiCad 9 打开时先提示“文件由较旧版本创建”，再报解析错误（v0.2.1 发布后发现） | `build.py` 生成后用 `kicad-cli` 把原理图和 `replica.kicad_sym` 改写为 KiCad 10 原生格式（`20260306` / `20251024`）。网表、ERC、与 PCB 的一致性和图面都不变 |
| Debian KiCad 10.0.6 的 `pcbnew` 模块（Python 3.14）遍历走线、图形时报错，`check_v02.py` 等脚本无法运行 | `gen/kicad_compat.py` 补上 `SwigPyIterator.next`，所有用到 `pcbnew` 的脚本都导入它 |
| KiCad 10 下进程内铺铜不可用：`WriteDRCReport` 段错误；只用 `ZONE_FILLER` 则读不到 `.kicad_dru`，少铺约 185 mm² 并出现 16 个间距错误 | 统一用 `kicad-cli pcb drc --refill-zones --save-board` 重铺（`gen/fp_update_v02.py --refill`）。`finish_v02.fill()` 在 KiCad 10 下直接报错提示 |

迁移前后（`checks/board_diff.py` 对比 v0.2 与 v0.2.1）：

- 910 个焊盘的铜皮、网络和铺铜连接方式全部不变；4886 段走线、378 个过孔不变；没有器件移动或换面。
- 丝印只在 U2（正面）和 Q1–Q3、T1（背面）随新库变化。装配层（F.Fab / B.Fab）分别有 139 / 19 个器件随新库变化，不进入 Gerber。
- 审查指标（`gen/check_v02.py`）逐项与 v0.2 相同；网表只有 U1 的封装字段改为项目库。
- 同一套门禁跑 v0.2：ERC 和指标通过；DRC 有 6+199 项未通过；铺铜一项未通过，KiCad 10 重铺后 GND 最多变化 70.6 mm²。

一次性迁移由 `gen/migrate_kicad10.py` 完成。之后又在 KiCad 10 下重跑了 `build.py`、`validate.py`、`fp_update_v02.py --outdated` 和 `--refill`。

## v0.2 对 v0.1 审查意见的处理

| 审查项 | v0.1 | v0.2 |
| --- | --- | --- |
| 无源件尺寸（根因） | 全部改成 0402 | 按 PDF 焊盘间距恢复：0201 ×134、0402 ×11、0603 ×7，LCSC 料号随之更换 |
| 散热焊盘过孔 | 无 | U1 3×3（ThermalVias 封装）、UP1 3×3 GND、U8 3×3 AGND、U6 3 个 AGND（第 4 个避让 TP17）、U2 2 个 |
| DC-DC 开关节点 | LX1 0.10 mm | LX1 0.38 mm（受 0.4 mm 引脚间距限制）、1.67 mm、锁定预布；DCDC5 开关节点 PMU_SW5 全程 0.35 mm、3.2 mm |
| 射频 / C9 | C9 移位形成残桩 | C9 回原位，距 U1 pin 1 1.19 mm；J2→C8→L1→C9→U1 全在 F.Cu、无过孔，0.35 mm（入脚 0.2 mm），射频铜共 11.0 mm |
| H2/H4 | 接地触点 | 1.6 mm 金属化孔、2.35 mm 焊盘、接 GND（由 PDF 焊盘距板边约 1.45 mm 与产品照片推断，须实物核对） |
| In1 | GND 层中有 44 个网络的局部走线 | 完整 GND 平面：0 条走线，填充为单一连通区，只有过孔反焊盘 |
| USB | 未成对、绕线长 | 本地成对重布：USB-C 的 D+ 两焊盘经两个过孔在 F.Cu 桥接，D− 两焊盘在 B.Cu 环接；U9 直通。USB_P 13.3 mm / 3 过孔，USB_N 15.3 mm / 4 过孔（含 P1/P2 测试点支线） |
| 功放输出 | PA_OUT 0.1 mm | PA_OUT ≥0.35 mm，喇叭线 SPK_P/N ≥0.3 mm |
| 器件面别 | 部分无源件挪到另一面 | 202 个器件全部与原图同面（F 159 / B 43） |
| 生产文件 | 无嘉立创格式 | `exports/jlc/` 提供 BOM（Comment/Designator/Footprint/LCSC Part #）和 CPL（Designator/Mid X/Mid Y/Layer/Rotation） |
| Apache 声明 | 不完整 | 新增 `NOTICE.md`；原理图与 PCB 标题栏注明 “Derived from … (Apache-2.0); modified” |

去耦距离与原图对比（引脚到同网络电容焊盘，mm）：U1.2–C20 1.84→1.86，U1.20–C13 1.02→1.28，U1.29–C4 3.95→3.99，U1.55–C2 2.32→2.32，U1.56–C1 2.49→2.46，UP1.23–CP3 4.19→4.13，UP1.33–CP8 3.99→3.95，U6.11–C52 2.07→2.05，U8.22–C105 1.63→1.63，U8.23–C106 1.39→1.38，U8.24–C101 1.64→1.65，U7.6–C56 1.90→1.83。

## v0.2 的取舍与其它变更

- **0.30/0.15 mm 出线过孔 ×13。** ESP32-S3 西侧和南侧引脚间距 0.4 mm，原位去耦电容列（C20/IND1/C19/C16）与引脚之间只容一列过孔；0.45 mm 过孔做不到每脚一个，出线会互相堵死。这 13 个小过孔（0.1 mm 铜间距、0.25 mm 孔间距、0.2 mm 孔到铜）每脚一个；其余 365 个为 0.45/0.20 mm。嘉立创能力表（2026-10-08 查询）注明 0.15 mm 孔要加价；工程最小过孔规则相应设为 0.30/0.15 mm。
- **地连接。** GND/AGND 焊盘尽量各配就近过孔：GND 过孔落在 In1 平面，AGND 过孔连接 F/B/In2 的 AGND 铺铜。另有板边环和铺铜网格缝合过孔，共 GND 63 个、AGND 50 个。AGND 与 GND 仍只经 R32 相连。
- **射频间距。** 射频铜与他网走线、铺铜 ≥0.25 mm，与非 GND 过孔 ≥0.5 mm（布线后发现 MIC2_N、GPIO17 等过孔离馈线 0.26 mm，已移开）；天线净空区内除馈线外无铜。射频线 1 mm 内有 3 个 GND 过孔（C8 接地端、L1 下方）。匹配网络西侧是 MCU 向北走线的主通道（在 In2/B，与馈线之间隔着 In1 地平面），放不下完整过孔围栏。
- **电源线宽。** 布线后逐段加宽：主干 0.3–0.5 mm，细间距引脚处保留 0.2 mm 颈缩。VBUS 从 USB-C 到 AXP2101 的输入路径 29 mm 为 0.4–0.5 mm，0.2–0.25 mm 只在引脚颈缩处；去板顶 TP2 测试点（原图位置）的约 25 mm 支线不走电流，多为 0.2–0.25 mm。DCDC5 开关节点 PMU_SW5 为 0.35 mm。各网络分布见 `validation/power-widths-v0.2.json`。
- **摆放。** 布线完成后 C56/C57/C71 放回原位。仍偏离 PDF 位置 >0.6 mm 的有 9 个：Key1/Key2、H1、J1 是替代件，按其机械结构摆放；CP6/RP3（不装）、CP7、RP4、C13 的原位压在 U1/U2 的 KiCad 标称庭院内，偏移 0.75–1.95 mm。
- **丝印与封装。** 测试焊盘去掉 1.5 mm 丝印圈；U9 改用 `SOT-666_Tight`，去掉压到 TVS1 焊盘开窗的 pin 1 箭头，F.Fab 保留倒角标记；H1 USB-C 外壳槽孔恢复全部铜层（翻面时 KiCad 会丢掉内层）。
- **自定义规则（`.kicad_dru`）。** 射频到铺铜/走线 0.25 mm、到非 GND 过孔 0.5 mm；天线净空区只允许射频馈线；小焊盘允许单辐条热连接。

## 电路变更（相对上游，与 v0.1 相同）

- **USB ESD：** U9 USBLC6-2P6 连接 D+/D−、VBUS 和 GND，保留原 R13/R14 串联电阻。
- **电池反接：** Q1 AO3400A 串在电池负极；Q2 AO3401A、Q3 MMBT3904、R49/R52/R53 和 C108 检测反接并关断 Q1。按 [ADI AN171 图 4](https://www.analog.com/en/resources/app-notes/an-171.html) 的思路适配单节锂电。新电路完成连接审查，尚未测量充电、反接热插拔瞬态或温升。
- **电池负极隔离：** J1.2 是 `BAT_NEG`，不能连接到外壳、USB 地或另一条外部接地线，否则会旁路 Q1。J1 的机械焊脚仍接 GND。
- **功放供电：** 默认只装 R50，维持原板 3.3 V；R51 不装。只有另行核验喇叭功率、芯片供电与回采幅度后才能改用 VSYS，且必须拆 R50。不得同时装两只。
- **开关封装：** Panasonic EVPAE 的 1 和 1′ 共用接点，另有外壳接地脚，已映射到原图的接地触点。它是候选替代件，板框已按其沉入结构增加避空，须核对原壳按钮行程。

## PCB 约束

四层分工：F.Cu 信号/器件，**In1.Cu 完整 GND 平面**，In2.Cu 信号加 GND/AGND 铺铜，B.Cu 信号/器件。模拟区（ES8311、ES7210、NS4150B、AEC 网络、MIC2 及 MIC1 一角）在 F/B/In2 铺 AGND。GND 铺铜轮廓本身挖去这些区域，不依赖铺铜优先级（v0.2.1）。天线区在各层禁止铺铜，内层与背面禁止走线，正面只留射频馈线。

制造规则：最小线宽/铜间距 0.10 mm，孔到异网铜 0.20 mm，孔到孔 0.25 mm，铜到板边 0.20 mm；过孔 0.45/0.20 mm（U1 出线处 0.30/0.15 mm）。射频 0.35 mm 与 USB 的阻抗都是待板厂叠层确认的设计值，**不是已验证的 50 Ω / 90 Ω 阻抗**。USB 是全速 12 Mbit/s，对阻抗不敏感。板框主轮廓由 PDF 推算，圆弧半径约 23.10 mm。

## 打样前需要补齐的资料或测量

| 项目 | 尚未证实的内容 |
| --- | --- |
| 原壳与 PCB | 主板比例、板厚、卡位、USB 深度、按键缺口和行程；H2/H4 孔径与是否金属化 |
| AMOLED FPC | 候选 31P 0.3 mm 连接器的接触面、pin 1 方向、排线厚度、插入深度 |
| 天线 | 原厂型号未知；候选 RFANT3216120A5T、保留的 L/C 值和 46 mm 板/铝壳组合需要 VNA 与无线测试 |
| 麦克风 | 原厂料号未公开；MSM381AKT003 为候选，需核对供电、灵敏度、声孔、封装高度及密封 |
| 电池与电源 | 反接保护冷插/热插、USB 在先/电池在先、充电转恒压、低电压启动、温升；RP4 测的是板温，不是电芯温度 |
| 生产 | 嘉立创对 0.15 mm 孔的加价与工艺确认；CPL 旋转角须在嘉立创预览逐件核对（QFN/SOT/DFN 的 pin 1、二极管极性） |
| 整机 | 上电电流、3.3 V 各路、下载、显示/触摸、双麦/功放、I2C、Wi-Fi、充电和休眠功耗 |

## 重现方式

主流程只需要系统 KiCad 10.0.6（`kicad-cli`、`/usr/share/kicad` 与系统 `pcbnew` Python 模块）和系统 `python3`，不需要额外安装 Python 包。PNG 预览优先用 CairoSVG，没有时用 KiCad 依赖的 wxPython 渲染。

```bash
python3 gen/build.py                                   # 原理图、项目库、BOM
kicad-cli sch export netlist --format kicadxml -o validation/netlist.xml s3-amoled-175.kicad_sch
python3 gen/validate.py                                # 连通性与封装核对、bom-assembly.csv
python3 gen/fp_update_v02.py --outdated                # 库有变化时更新板上封装（焊盘必须完全相同）
python3 gen/sync_fields.py                             # 符号字段同步到封装
python3 gen/fp_update_v02.py --refill                  # 用 kicad-cli 重铺铜（加载 .kicad_dru）
python3 checks/run_checks.py                           # 合并门禁：ERC、DRC+一致性、铺铜、指标、生成器复现
kicad-cli sch erc --format json --severity-all -o validation/erc.json s3-amoled-175.kicad_sch
kicad-cli pcb drc --format json --schematic-parity --severity-all -o validation/drc.json s3-amoled-175.kicad_pcb
python3 gen/export_v02.py                              # DRC/ERC 干净时才导出
```

在 KiCad 里改版图后，提交前运行 `python3 checks/run_checks.py`。改动前后可用 `python3 checks/board_diff.py 旧.kicad_pcb 新.kicad_pcb` 对比。原工程的 CI 在 `kicad/kicad:10.0.6` 容器里跑同一套门禁；打版本标签时另生成审查包。该工作流尚未在实际 runner 上验证。

可选的 Python 依赖用 uv 管理，声明在 `pyproject.toml`，锁定在 `uv.lock`。执行一次 `uv sync`，会在仓库内建 `.venv` 并装上三组依赖：

- `routing`：NumPy、Shapely，供 v0.2 的布线脚本使用；
- `pdf`：PyMuPDF、NumPy，供 `gen/pdf/` 和 `gen/extract_placement.py` 从原厂 PDF 提取数据；
- `preview`：CairoSVG，用于 PNG 预览。

之后用 `uv run python gen/pdf/pdf_netlist.py` 这样的方式运行脚本。

`pcbnew` 是按系统 Python 编译的，所以 `pyproject.toml` 禁止 uv 下载自己的 Python，`.venv` 直接用 `/usr/bin/python3`（3.14）。脚本会自己把系统 `dist-packages` 加进路径来导入 `pcbnew`。在 Windows 或 macOS 上，要先用 `uv venv --python <KiCad 自带的 python>` 建好 `.venv`，再执行 `uv sync`。

在 KiCad 10 环境下用 uv 重跑 PDF 提取，结果与 `data/` 逐字节一致。v0.2 的布线修复脚本依赖进程内铺铜，在 KiCad 10 下会报错停止，只作为过程记录保留。布线用的 Freerouting 2.5.0（Java）不随工程保存。

**最终 PCB 是保存的交付物，不是一键生成的结果。** v0.2 的布线过程：

1. `pcb_v02.py` 按 PDF 位置摆放，`project_rules.py` 写规则，`preroute_v02.py` 预布并锁定 EP 过孔、射频链和 LX1。
2. Freerouting 2.5 做第一遍布线，`finish_v02.py` 导入并铺铜。
3. `repair_v02.py` 用 KiCad DRC 驱动 A* 网格布线器（沿用 v0.1 的 `finish_routing.py`，加入 In1 禁布、射频间距、天线区和拥塞记忆）反复拆线重布。
4. 针对瓶颈的步骤：`ground_v02.py`（焊盘地过孔）、`usb_v02.py`（USB 对）、`escape_vias_v02.py` 与 `escape_v02.py`（U1 有序出线）、`window_v02.py`（编解码器区局部重布）、`stitch_v02.py`、`pad_to_via_v02.py`、`reroute_width_v02.py`、`move_back_v02.py`、`widen_v02.py`、`fp_update_v02.py`。

这些步骤由 DRC 结果逐次驱动，重跑不会得到逐线相同的结果。**重新运行 `gen/pcb_v02.py` 会覆盖当前 PCB。**

## 资料来源与接手记录

上游 [Waveshare 仓库](https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.75C) 的 Apache 许可原文在 `sources/Waveshare-LICENSE`，派生与修改声明见 `NOTICE.md`。KiCad 库许可原文另存为 `sources/KiCad-*-copyright`。EasyEDA/LCSC 转换的封装与模型不在上游 Apache 许可范围内。

v0.1 由 Codex 完成；v0.2 根据会话 `2cacc33e-dbcb-490d-b18d-792d63648d76` 中对 v0.1 的审查意见重做 PCB，v0.2.1 的 KiCad 10 迁移在同一会话完成。未烧录或测量实物。
