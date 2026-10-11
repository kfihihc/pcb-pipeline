# KiCad 10 与本机环境的已知问题

本机：Debian 的 KiCad 10.0.6（`kicad 10.0.6+dfsg-1`）和 Python 3.14。所有条目都在 S3 复刻或 pcb-pipeline 的示例工程里实测过；pcbkit 已经处理的，注明了处理位置。

| 问题 | 表现 | 处理 |
| --- | --- | --- |
| SWIG 迭代器缺 `next` | `board.GetTracks()`、`GraphicalItems()` 一遍历就报 AttributeError | 先 `import kicad_compat`（pcbkit 已处理） |
| 进程内铺铜不可用 | `WriteDRCReport` 段错误；单用 `ZONE_FILLER` 读不到 `.kicad_dru` | 一律用 `kicad-cli pcb drc --refill-zones --save-board` 重铺 |
| 铺铜优先级语义变了 | 低优先级区会铺进高优先级区没铺到的地方（S3 的 GND 铺进了 AGND 区域，多出约 165 mm²） | 分割区域直接从铺铜轮廓里挖掉，不依赖优先级 |
| `.kicad_dru` 有一处写错 | 整份规则被静默丢弃：DRC 0 违规、退出码 0、没有任何提示 | 门禁 rules 检查加一条哨兵规则，哨兵不触发就判失败 |
| `pcbnew.SaveBoard` | 会改写同名 `.kicad_pro` | 保存前读出工程文件，保存后写回（pcbkit 各脚本已处理；board_setup 只合并 board 段） |
| 网络名转义 | 板上存 `{slash}`，网表导出时是 `/` | 比较网络名前先还原转义（`common.unescape`） |
| 局部标签 | 网络名带路径前缀 `/NET` | 生成的原理图一律用全局标签，网络名与代码完全一致 |
| 没有工程文件 | `kicad-cli` 不读工程级库表，ERC 报 lib_symbol_issues | sch_gen 会补一个最小的 `.kicad_pro`；工程自带 sym-lib-table/fp-lib-table |
| 旧格式文件头 | SKiDL 等工具写出旧版本号的文件，KiCad 9 打不开混合格式 | `kicad-cli sch upgrade --force`（sch_gen 已处理） |
| 3D 模型变量 | `${KICAD9_3DMODEL_DIR}` 不再被解析 | 改用 `${KICAD10_3DMODEL_DIR}`；本机没装 `kicad-packages3d`，所以渲染图和 STEP 里没有模型 |
| 封装与库比较 | `FootprintNeedsUpdate(lib, 1)` 等同于 DRC 的 lib_footprint_mismatch；参数 0 时还会报 DNP 器件 | 用参数 1 |
| `FOOTPRINT.Flip()` | 在加入板子之前调用会段错误；翻面时 PTH 焊盘会丢掉内层 | 先 `board.Add()`，再 Flip；翻面后检查焊盘层 |
| `GetBoardEdgesBoundingBox` | 包含板框线宽，以它为原点会偏半个线宽 | 用 `kicad_compat.outline_origin()` |
| CI 镜像 | `kicad/kicad:<版本>` 是 Debian 13，默认用户 kicad，没有 python3 | 工作流里用 `--user root` 并 `apt-get install python3` |

## 外部工具

- **KiCadRoutingTools**（v0.22.1 实测）：
  - 不读 `.kicad_dru` 自定义规则。要让它遵守的约束，必须写成禁布区或网络类，或通过 `--net-clearances <json 文件>` 传入（这个参数要的是文件路径，不是 JSON 字符串）。
  - 默认会改写输出旁边的 `.kicad_pro`，把 DRC 下限降到它实际做到的值。要加 `--no-fix-drc-settings`，而且只采纳它输出的 `.kicad_pcb`。
  - 电源网络在细间距焊盘处会自动颈缩，多点连接的分支按默认线宽走。
- **Freerouting 2.5**（S3 实测）：
  - 后几轮越跑越差，最终保存的是最后一轮而不是最好的一轮；
  - 会自动颈缩到 0.075 mm；
  - 已有走线当作固定物；
  - 需要 Java（本机没装）。
- **KiKit 1.8.1、PcbDraw 1.3.0、KiBot 1.9.1**：直接运行都报 `'SwigPyIterator' object has no attribute 'next'`。先 `import kicad_compat` 再调用它们的入口（`pcbkit/extras.py` 已处理）。uv 环境看不到系统的 pcbnew，kicad_compat 会把系统 dist-packages 加到 `sys.path`。
- **KiKit 拼板**：
  - 输出目录要先建好；拼板目录里没有 `fp-lib-table`、`sym-lib-table` 时，DRC 会把每个封装都报成 lib_footprint_issues，所以要拷过去；
  - 拼出来的板要用 `kicad-cli pcb drc --refill-zones --save-board` 重铺并检查；
  - **DRC 干净不等于拼对了**：连接桥一个都没生成时，板子是悬空的，DRC 照样 0 违规。要检查拼板外框只有一块（`GetBoardPolygonOutlines` 后 `OutlineCount() == 1`）；
  - `fixed` 连接桥：`vcount` 是上下边的桥数，`hcount` 是左右边，宽度用 `vwidth`、`hwidth`（`width` 只对 corner 类型有效）；
  - 板边悬伸的连接器（USB-C）旁边不能放连接桥，否则邮票孔落进庭院（`npth_inside_courtyard`）；
  - 拼板 CPL 每块子板重复同一位号；给 `layout.renameref` 改名后，位号与单板原理图对不上，`kikit fab` 输出的 BOM 和 CPL 会变成空的。
- **InteractiveHtmlBom 2.12.0**：pip 包声明依赖 wxPython，本机从源码编译会失败；它只在设置对话框里用到 wx。工程 pyproject 用 `override-dependencies = ["wxpython; sys_platform == 'never'"]` 去掉这个依赖，运行时设 `INTERACTIVE_HTML_BOM_NO_DISPLAY=1`，否则报 “Unable to access the X Display”。包一导入就 `import pcbnew`，探测是否安装要用 `importlib.util.find_spec`。页面里的数据经 LZString 压缩，带生成时间。
- **PcbDraw**：自带的器件图库没有 USB-C、SOT-89 等，这些只画焊盘（`extras.py` 列出来）；svgpathtools 在 Python 3.14 下打印 SyntaxWarning，无害。
- **KiCanvas**（kicanvas.org 构建，2026-04-28）：正确显示 KiCad 10 的原理图（多页）和 PCB；浏览器不允许 `file://` 读取工程文件，要用 HTTP 打开；断网时图纸照常显示（字体内置），工具栏图标退化成文字（图标字体来自 fonts.googleapis.com）。
- **kicad-happy v2.3.1**：分析脚本只用标准库；会在当前目录写 `capability_mode.json`，所以在临时目录里运行；用 `-o` 指定输出，不用 `--analysis-dir` 的时间戳缓存。没有信号走线的板子会出一条 GP-001 info（“回流路径数据不可用”），属正常。
- **KiBot 1.9.1**：只认它作者维护的 iBOM 分支，找不到就尝试自动下载；AGPL-3.0。未引入。
- **SKiDL 2.3**：
  - 自带的原理图生成器在 11 个器件的板子上就会 RoutingFailure，小电路也挤成一团，所以改用 pcbkit 的 sch_gen；
  - 网表里带日期和 “SKiDL Line” 行号，要用 `sch_gen.py --normalize-input` 清除；
  - 自定义字段要写进 `part.fields[...]`。
- **LCSC 和嘉立创数据**：
  - 零件库里的数据手册链接常常指向网页查看器，要用 LCSC 接口返回的 `pdfUrl`；
  - 有的器件没有 PDF 直链，应改用原厂资料；
  - Farnell 的 CDN 会把非浏览器的 User-Agent 挂起。
- **pdftotext**：会把单词粘在一起（例如 “AbsolutemAximum”），检索时词间空白要可有可无（`datasheet.py grep` 已处理）；纯矢量图页没有文字，要渲染成图片来读。
