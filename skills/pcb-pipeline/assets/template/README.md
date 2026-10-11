# {{title}}

{{name}}：用 pcb-pipeline 流程管理的 KiCad {{kicad}} 工程（pcbkit {{kit_version}}）。许可：{{license}}。

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
python3 pcbkit/board_diff.py old.kicad_pcb hw/{{name}}.kicad_pcb --scope docs/changes/0001-x.toml
python3 pcbkit/review.py                  # 审查包 reports/review/（另含 KiCanvas、iBOM、PcbDraw 板图、EMC 线索、拼板）
python3 pcbkit/extras.py status           # 可选输出（pcb.toml [outputs]）要哪些、工具装了没有、拼板定了没有
python3 pcbkit/release.py                 # 门禁通过后生成制造与审查包 release/
```

改动流程：分支 → 变更单 `docs/changes/` → 修改 → 门禁 → PR（附报告与版图对比）→ 人工审查合并。详见 pcb-pipeline 技能。
