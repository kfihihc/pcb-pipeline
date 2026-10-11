# 示例：接管已有工程（S3 AMOLED 复刻）

把 pcb-pipeline 的门禁套到已有的 KiCad 工程上，不改任何设计文件。对象是 S3 AMOLED 复刻工程（ESP32-S3-Touch-AMOLED-1.75C 的 KiCad 复刻，另一个仓库；v0.2.1，KiCad 10.0.6，4 层，202 个器件），下文记作 `<S3 仓库>`。

本目录只有配置，没有动 S3 仓库：

- `pcb.toml`：文件位置、生成器命令、2 条 ERC 例外（原设计 IMU 辅助总线接 VCC3V3）、BOM 字段要求、1 条 BOM 豁免；
- `checks/metrics.toml`：S3 自己 `checks/thresholds.json` 里的 30 条阈值，改写成声明式指标（29 条声明式加 1 条引用 `gen/check_v02.py`），另加 1 条 In1 地平面单块。

## 怎样套用

```bash
P=<pcb-pipeline 仓库>
python3 $P/skills/pcb-pipeline/scripts/new_project.py <S3 仓库> --adopt \
    --pcb s3-amoled-175.kicad_pcb --sch s3-amoled-175.kicad_sch --name s3-amoled-175
cp $P/examples/s3-adoption/pcb.toml <S3 仓库>/
cp $P/examples/s3-adoption/checks/metrics.toml <S3 仓库>/checks/
cd <S3 仓库> && python3 pcbkit/gate.py
```

`--adopt` 不覆盖已有文件，也不添加 README、CI 工作流和 `layout/` 模板，因为 S3 已经有自己的 CI 工作流（`hw-checks.yml`）。决定改用 pcbkit 门禁后，再把 CI 的命令换成 `python3 pcbkit/gate.py`。这一步要在 S3 仓库里开分支做，作为单独的变更。

## 2026-10-10 在副本上的验证

| 检查 | 结果 | 与 S3 自己的 `checks/run_checks.py` 相比 |
| --- | --- | --- |
| erc | PASS（2 条警告均在例外表中） | 相同 |
| drc + 一致性 | PASS（0/0/0） | 相同 |
| rules | PASS（5 条自定义规则已加载，哨兵触发 199 次） | **新增** |
| zones | PASS（重铺变化 0.0000 mm²） | 相同 |
| netlist | PASS（202 个器件的引脚与焊盘一一对应；BOM 字段齐全） | **新增**。首次运行查出 H3（喇叭，导线手焊）标为装配却没有 LCSC 料号，已写入豁免并注明理由 |
| metrics | PASS（30 条） | 与原有 30 条阈值等价；另加 In1 地平面单块 |
| reproduce | PASS（gen/build.py、网表导出、gen/validate.py） | 相同 |

用时约 20 秒，比 S3 原门禁（17 秒）多出的时间花在规则哨兵和焊盘核对上。

反向测试（在副本上故意改坏，测完已还原）：

- LX1 开关节点 5 段走线改成 0.2 mm → metrics 失败：`min_width_mm LX1 = 0.2 < 0.3`。
- `.kicad_dru` 里的 `(constraint min_resolved_spokes 1)` 改成 `(min 1)` → rules 失败（整份规则文件没有加载）。规则被丢弃后，原本放行的单辐条热焊盘还引出了 9 项 DRC 违规。
