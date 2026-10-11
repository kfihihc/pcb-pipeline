# 参考设计从哪里找

链接会变。下面只有标注“已核实”的条目在本机实际下载过，其余都要到厂商官网搜索产品页（“Design resources”“Hardware design”“Evaluation board”“Reference design” 栏目）。下载后在 `refs/<名>/source.json` 记录链接、日期、版本和 SHA-256。

| 厂商 | 常见形式 | 格式 | 备注 |
| --- | --- | --- | --- |
| Raspberry Pi（RP2040/RP2350） | “Hardware design with RP2040” 和最小系统设计 | **KiCad 工程**（已核实：`https://datasheets.raspberrypi.com/rp2040/Minimal-KiCAD.zip`，2026-10-10 下载，R3 版，37 个器件），附 PDF 和 BOM | MIT 许可（LICENSE.txt，Copyright 2026 Raspberry Pi Ltd），注明仅供参考、不保证 |
| Espressif（ESP32 系列） | 开发板原理图、硬件设计指南 | 多为 PDF；部分开发板有 PCB 源文件 | 硬件设计指南里有射频匹配、晶振、启动配置引脚的要求 |
| STMicroelectronics | Nucleo/Discovery 板、AN（如 AN2867 晶振设计） | PDF 原理图，部分板有 Altium/Gerber | 应用笔记比评估板更适合抄外围电路 |
| Texas Instruments | EVM 用户指南、TI Designs 参考设计 | 用户指南 PDF 内含原理图、版图和 BOM；部分有 Altium 文件 | EVM 常带测试跳线和测量点 |
| Analog Devices / Maxim | 评估板、应用笔记（S3 反接保护参考了 AN171） | PDF，部分有 Altium/Allegro | — |
| Nordic、Silicon Labs 等无线 SoC | 参考布局、射频匹配 | PDF 加 Gerber/Altium；部分有 KiCad | 射频部分照抄版图，不只照抄原理图 |
| 开源开发板（Adafruit、SparkFun、Waveshare 等） | GitHub 仓库 | EAGLE、KiCad、PDF | 许可各不相同（CC-BY-SA、Apache、MIT），派生要遵守。S3 派生自 Waveshare（Apache-2.0） |

格式处理：

- KiCad 6 及以上的工程：`refnet.py export` 直接读（kicad-cli 10 能读旧版本格式）。KiCad 5 的 `.sch` 要先用 KiCad GUI 转换。
- Altium `.PcbDoc`、EAGLE `.brd`、PADS、CADSTAR、Fabmaster、P-CAD：`kicad-cli pcb import` 能读 PCB（`refnet.py` 会自动调用）。原理图格式要在 KiCad GUI 里导入，命令行不支持。
- 只有 Gerber：没有网络信息。IPC-D-356 或 ODB++ 里有网络，但目前没有现成的导入方法，按 PDF 处理。
- PDF：按 SKILL.md 的“只有 PDF 的参考设计”手工转录。
