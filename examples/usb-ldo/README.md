# USB-C 3.3 V LDO demo

> **这是 pcb-pipeline 的端到端示例**：一块 25 × 18 mm 的双层板（USB-C 取电 → HT7533-1 → 3.3 V 和指示灯），2026-10-10 按流程从零做到制造包，全部步骤由脚本完成。它的价值在于流程在各阶段实际拦下的问题，下表逐条列出：
>
> | 阶段 | 发现了什么 | 证据 |
> | --- | --- | --- |
> | 选料 + 仿真 | XC6206 的 VIN 绝对最大值 7.0 V，热插拔峰值 7.6–8.2 V，改用 HT7533-1 | `sim/benches.toml`、D-0002 |
> | 数据手册 | HT7533-1 保证输出只有 70 mA（首页写 100 mA），需求改为 50 mA；立创中文站给的同名 PDF 是另一家厂商的 | `data/parts/HT7533-1/facts.toml` |
> | 数据手册 | LED 原厂引脚编号与 KiCad 相反；USB-C 推荐焊盘是按 1.0 mm 板厚画的 | facts 的 caveat、`docs/reviews/` |
> | 选料 | 每套物料 1.03 美元，超出 0.5 美元目标（连接器占 0.91 美元） | `jlc_parts.py check`、D-0003 |
> | 规则 | 自定义 VBUS 间距规则与 USB-C 焊盘自身的间距冲突 | DRC |
> | 布线 | 自动布线在 USB 外壳下走细线、打盘中孔、无视 `.kicad_dru`；改成禁布区加预布线 | metrics、变更单 0001、D-0005 |
> | 工具 | 摆位原点偏了半个板框线宽（25 µm），修正后用 `layout/rebuild.sh` 重建 | 变更单 0002 |
> | 拼板 | 2×2 试拼时邮票孔落进 USB-C 庭院；连接桥参数写反时板子在拼板里悬空，DRC 却照样干净，改为检查拼板外框只有一块 | D-0006、`layout/panel.toml` |
> | EMC 预检 | kicad-happy 指出 J1 附近没有 ESD 和滤波（IO-001），与 D-0004 的取舍一致，产品化时要加 | `reports/review/emc.md` |
>
> 最终门禁 8 项全过；`release/` 的包标为 REVIEW ONLY，因为它不是从 git 提交生成的。包里另有自拼的 2×1 拼板（`fab/panel/`）、交互式 BOM 和 KiCanvas 页面。

usb-ldo：用 pcb-pipeline 流程管理的 KiCad 10.0.6 工程（pcbkit 0.2.0）。许可：CERN-OHL-S-2.0。

| 位置 | 内容 |
| --- | --- |
| `pcb.toml` | 工程清单：文件位置、门禁与 BOM 配置 |
| `docs/` | 需求（SPEC）、设计决定（DECISIONS）、修订记录、审查清单、上电记录、变更单 |
| `parts/parts.csv`、`data/parts/` | 选料登记表；每个器件的数据手册与带页码的事实 |
| `design/` | 设计意图：电路代码（code 模式）与连接意图断言 |
| `hw/` | KiCad 工程：原理图、PCB、自定义规则 `.kicad_dru` |
| `layout/` | 板框、层数、制造下限、网络类、固定摆位；拼板预设 `panel.toml` |
| `checks/metrics.toml`、`sim/` | 项目指标与仿真基准，都进入门禁 |
| `pcbkit/` | 随工程固定版本的工具（门禁、同步、摆位、仿真、审查、发布、可选输出）；用 pcb-pipeline 的 `new_project.py --update-kit` 升级 |

## 常用命令

```bash
uv sync                                   # 可选依赖（SKiDL 等）
uv sync --group extras                    # 可选输出用的 KiKit、InteractiveHtmlBom、PcbDraw（之后单独 uv sync 会把它们去掉）
uv run python design/board.py             # code 模式：由代码生成原理图
python3 pcbkit/board_setup.py             # 按 layout/board.toml 建立或更新板框、层数、规则
python3 pcbkit/sync_pcb.py                # 原理图 -> PCB（封装、网络、字段），不动已有布局
python3 pcbkit/place.py                   # 按 layout/placement.toml 摆放并锁定关键器件
python3 pcbkit/gate.py                    # 合并门禁：ERC、DRC+一致性、规则哨兵、铺铜、连接意图、指标、仿真、复现
python3 pcbkit/board_diff.py old.kicad_pcb hw/usb-ldo.kicad_pcb --scope docs/changes/0001-x.toml
python3 pcbkit/review.py                  # 审查包 reports/review/（另含 KiCanvas、iBOM、PcbDraw 板图、EMC 线索、拼板）
python3 pcbkit/extras.py status           # 可选输出（pcb.toml [outputs]）要哪些、工具装了没有、拼板定了没有
python3 pcbkit/release.py                 # 门禁通过后生成制造与审查包 release/
```

改动流程：分支 → 变更单 `docs/changes/` → 修改 → 门禁 → PR（附报告与版图对比）→ 人工审查合并。详见 pcb-pipeline 技能。
