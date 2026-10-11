# KiCadRoutingTools 使用要点（v0.22.1 实测）

项目地址：<https://github.com/drandyhaas/KiCadRoutingTools>，MIT 许可，个人主导。它用基于真实开源板的语料做回归测试，2026-10 的发布节奏约每两周一次。新版本先在分支上试，比较完成率、过孔数和指标，确认没问题再改 `setup_krt.sh` 的默认版本。

## 安装与调用

- `setup_krt.sh [tag]`：克隆到 `~/.cache/pcb-pipeline/KiCadRoutingTools-<tag>`，下载预编译的 `grid_router` 动态库（Linux x86_64，不需要 Rust），用 uv 建 `.venv` 并安装 numpy、scipy、shapely（系统 Python）。
- 工程里通过 `pcbkit/route.py` 调用，它会读 `layout/route.toml`。需要额外参数时写进 `extra_args`。

## 常用参数

| 参数 | 作用 | 备注 |
| --- | --- | --- |
| `--nets "*" "!GND"` | 选网络（fnmatch，`!` 表示排除） | 已经连通的网络会自动跳过 |
| `--track-width`、`--clearance`、`--via-size`、`--via-drill` | Default 网络类的布线参数 | 非 Default 网络类从 `.kicad_pro` 读取 |
| `--power-nets A B --power-nets-widths 0.5 0.4` | 电源网络加宽 | 进细间距焊盘时会自动颈缩；多点连接的分支按默认线宽走 |
| `--no-power-tap-neckdown` | 禁止颈缩重试 | 可能导致布不通 |
| `--net-clearances <file.json>` | 每个网络的间距，格式 `{"VBUS": 0.3}` | **要的是文件路径**；`route.py` 会自动写这个文件 |
| `--no-fix-drc-settings` | 不改写输出旁边的 `.kicad_pro` | `route.py` 一定会加 |
| `--keep-input-copper` | 输入板上已有的铜皮在清理时保持不动 | 链式流程有用 |
| `--rip-existing-nets PATTERN` | 允许拆掉已有的（未锁定）走线 | 默认不拆 |
| `--group … --group-by sheet --preview --preview-png` | 按原理图页或分组局部布线并预览 | 局部重布 |
| `--undo` | 把指定范围的铜皮拆回未布线状态 | 要明确范围 |

其他工具：

- `py_router/route_planes.py`（建电源和地平面并打过孔）；
- `route_diff.py`（差分对）；
- `bga_fanout.py`（BGA/QFN 扇出）；
- `py_placer/place_optimize.py --suggest-locks`（摆位建议）；
- `py_tools/render_placement.py`（摆位差异图）；
- 仓库自带的 Claude Code 技能 `/plan-pcb-routing`、`/diagnose-routing-failures`、`/review-routed-board`（在它的仓库目录里运行）。

## 实测到的问题

- 不读 `.kicad_dru` 自定义规则。日志的 `unsupported_rules` 会列出它不认识的规则名。
- 默认会把 `.kicad_pro` 里的 DRC 下限降到它实际做到的值（日志里能看到 “In-run DRC floors… lowered”），这等于替我们放宽了规则。
- 多点连接的分支默认用基础线宽，所以电源网络会出现 0.25 mm 的连接段。关键电源网络要预布线。
- 会在细间距连接器的焊盘中心打过孔，以及从金属外壳下面绕线。连接器周边要用禁布区加预布线。
- 示例板（11 个器件、双层）上完整布线约 0.1–0.2 秒，大部分时间花在 KiCad 重铺和检查上。

## Freerouting（对照用）

需要 Java（本机没装，要用时请用户 `sudo apt install default-jre-headless`）。S3 用的是 2.5.0：

- 用 `--router.autorouter.max_passes=1`、`automatic_neckdown=false`、`copper_to_edge_clearance_um=200`；
- 它保存的是最后一轮，不是最好的一轮；
- 已有走线视为固定。

通过 DSN 导出、SES 导入，导入后同样要跑门禁。
