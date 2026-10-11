# 修订记录

每个修订列出：审查意见或需求 → 修改 → 证据（门禁报告、指标前后值、版图对比）。发布时打标签 `v<revision>`，制造包作为标签附件，附 SHA-256 清单。

## v0.1.0（未发布，2026-10-10）

首版，按 pcb-pipeline 从零完成（pcbkit 0.1.0，KiCad 10.0.6，KiCadRoutingTools v0.22.1）。

| 意见或需求 | 修改 | 证据 |
| --- | --- | --- |
| 选料：XC6206 的 VIN 绝对最大值 7.0 V，热插拔峰值 7.6–8.2 V | LDO 改为 HT7533-1（D-0002） | `sim/benches.toml` usb_hotplug；Torex p.3、Holtek p.2/p.5 |
| 数据手册：HT7533-1 保证输出电流只有 70 mA | R-02 改为 1–50 mA（D-0002） | facts.toml（p.5） |
| 成本：GCT 连接器 0.909 美元，超出 0.5 美元目标 | 目标改为 1.2 美元/套（D-0003） | `jlc_parts.py check`（2026-09-26 快照） |
| 布线：VBUS 在 USB-C 外壳下用 0.25 mm 绕线 | 外壳下禁布；VBUS 预布线并锁定（变更 0001、D-0005） | metrics vbus_min_width 0.25 → 0.5；DRC 0 |
| 工具：摆位原点偏 25 µm | pcbkit 修正，版图链重建（变更 0002） | 坐标文件 C1 = 113.000 |
| 审查：LED 引脚编号与 KiCad 相反 | 贴片预览时按阴极标记核对（BRINGUP 上电前检查） | KT-0603R facts caveat（p.2） |
