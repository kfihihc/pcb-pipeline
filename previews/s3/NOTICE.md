# NOTICE

本工程（S3 AMOLED 1.75C KiCad 复刻）派生自 Waveshare [ESP32-S3-Touch-AMOLED-1.75C](https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.75C) 公开的原理图与装配图。上游以 Apache License 2.0 发布，许可证原文见 [`sources/Waveshare-LICENSE`](sources/Waveshare-LICENSE)。上游仓库未提供 NOTICE 文件。

This project is a derivative work of the Waveshare ESP32-S3-Touch-AMOLED-1.75C hardware documentation, licensed under the Apache License 2.0 (copy in `sources/Waveshare-LICENSE`). All schematic and PCB files in this project were redrawn in KiCad and modified; each title block states "Derived from Waveshare ESP32-S3-Touch-AMOLED-1.75C schematic (Apache-2.0); modified".

## 修改声明（Apache-2.0 第 4(b) 条）

上游只公开 PDF，没有 PCB 源文件。本工程的 `.kicad_sch`、`.kicad_pcb` 均为重新绘制的派生文件，相对上游的主要改动：

- 用 KiCad 重新绘制 10 页原理图（v0.2 用 KiCad 9，v0.2.1 起为 KiCad 10）；保留原 GPIO 分配与器件位号。
- 新增 USB 数据线 ESD（U9）和电池反接保护（Q1–Q3、R49/R52/R53、C108）；功放供电保留原 3.3 V（R50 装、R51 不装）。
- 开关、麦克风、天线等原厂料号未公开的器件，采用候选替代料号与封装。
- PCB 按公开装配图的器件位置重新布局和布线（v0.1 → v0.2 → v0.2.1 的变更见 `README.zh-CN.md`）。

## 第三方资料

| 内容 | 许可 / 权利 |
| --- | --- |
| KiCad 标准符号与封装库（系统 `/usr/share/kicad`，及据其派生的 `lib/replica.kicad_sym`、`lib/s3amoled.pretty/*_Tight` 封装和固化的 KiCad 9 版 `QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm_ThermalVias`） | CC-BY-SA 4.0 附 KiCad 设计例外条款，见 `sources/KiCad-symbols-copyright`、`sources/KiCad-footprints-copyright` |
| `lib/lcsc.pretty` 等由 EasyEDA/LCSC 转换的封装与模型 | 不在上游 Apache 许可范围内，以 LCSC/EasyEDA 的使用条款为准 |
| Waveshare BSP 引脚定义 `sources/waveshare-bsp-pinout.h` | Apache-2.0，见 `sources/BSP-LICENSE` |
| `sources/` 中的器件数据手册与应用笔记 | 版权归各自厂商，仅作设计核对引用 |
