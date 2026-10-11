# 两轮审查的提示词模板

用子 agent 时，各开一个，互不共享中间结论；反方只看审查者写好的结论文件，不看审查者的推理过程。两者都只读，不改设计文件。

## 审查者

```
你在审查 KiCad 工程 <路径>（<板名> <版本>，<阶段>审查）。只读，不要修改任何设计文件。
材料：reports/review/packet.md、top.png、bottom.png、schematic.pdf、pcb.pdf、caveats.md、
docs/SPEC.md、docs/DECISIONS.md、parts/parts.csv、data/parts/*/facts.toml（每个数字带页码）、
design/intent.toml、checks/metrics.toml、sim/benches.toml。清单：docs/REVIEW-CHECKLIST.md。
要求：
- 逐项过清单。每条发现写：位置（位号、网络、坐标或页码）、证据（数据手册页码、指标或仿真数值、图上位置）、
  严重度（阻断、应改、建议、待确认）、建议的修改，以及能否变成门禁（指标、意图、仿真）。
- 门禁通过的项不要重复报，除非你认为检查本身有漏洞（要说明漏在哪里）。
- 没有证据的怀疑写成“待确认”，并说明需要什么信息。
输出：docs/reviews/draft-reviewer.md（表格）。
```

## 反方

```
你是反方审查者。读 docs/reviews/draft-reviewer.md，对每条结论：
- 找出证据不足、严重度定高了、根本不是问题的条目，给出理由（引用数据手册页码或计算）；
- 找出审查者漏掉的风险，尤其是：门禁通过但检查本身没有覆盖的情况；例外、阈值放宽或 BOM 豁免没有写理由；
  数据手册不是同一家厂商或同一个版本；仿真角点没有覆盖最坏情况；机械、热、射频这些审查本身判断不了的问题。
- 不要为了反对而反对：同意的条目写“同意”。
输出：docs/reviews/draft-devil.md。
```

## 合并

由主 agent 或人合并成 `docs/reviews/YYYY-MM-DD-<阶段>.md`：每条最终结论附处理方式（变更单编号、新增的门禁项、待确认项的负责人）。反方的不同意见保留在单独一段。草稿文件删除或归档到 `docs/reviews/drafts/`。
