# 变更单

agent 或人对设计的每次改动先写一张变更单 `NNNN-<短名>.toml`，再动设计文件。它是事务的“合同”：说明为什么改、允许改什么、怎样算改好。PR 描述引用它，审查者用 `pcbkit/board_diff.py --scope` 核对实际改动没有越界。

```toml
id = "0001"
title = "C2 靠近 U1 第 2 脚"
stage = "layout"                    # spec / parts / schematic / sim / rules / placement / routing / release
requirements = ["R-01"]
why = "去耦距离 3.1 mm，超过 2 mm 目标（checks/metrics.toml: dec_u1）"

[scope]                             # 版图改动只能落在这些位号和网络上（通配符可用）
refs = ["C2"]
nets = ["+3V3", "GND"]

[acceptance]                        # 怎样算完成
gate = "all"                        # 门禁全部通过
metrics = { dec_u1 = "<= 2.0" }     # 需要改善或保持的指标
notes = ""
```
