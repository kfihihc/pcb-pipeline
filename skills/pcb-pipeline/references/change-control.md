# 事务化改动：agent 怎样改设计

目标：每次改动都可追溯（为什么改）、有边界（改了什么，有没有越界）、可判定（门禁和指标说了算）、可回滚（一个分支、一个 PR）。做法综合了几个项目：

- Copperhead 的“spec 门控”：先有变更提案，才能动文件；
- Copperbrain 的“私有工作区 → 校验 → 显式接受”；
- copperbench 的“离线断言评分”；
- S3 复刻的实际教训。

## 权限分级

| 级别 | 允许 | 机制 | 谁批准 |
| --- | --- | --- | --- |
| L0 只读 | 读设计、跑门禁、渲染、写审查意见 | `docs/reviews/`、issue | 不需要 |
| L1 分支提案 | 改设计文本（SPEC、parts、design、layout、checks、sim、规则）并重新生成 | 分支 + 变更单 + 门禁 + 版图对比 + PR | 人工合并 |
| L2 受控自动化 | 摆位、预布线、自动布线、铺铜、封装更新 | pcbkit 脚本在副本上运行，结果通过 DRC 才采纳；锁定项不动 | 同 L1，PR 里附自动化的日志和统计 |
| 禁止 | 推送或合并主分支、打标签、手改制造文件、为过检放宽规则、采纳路由器写的 `.kicad_pro` | 分支保护、门禁、审查 | — |

## 一次改动的步骤

1. **开分支**：`git switch -c hw/<阶段>-<短名>`（并行时用 `git worktree add`）。
2. **写变更单** `docs/changes/NNNN-<短名>.toml`，格式见工程里的 `docs/changes/README.md`：
   - `why`：引用需求编号、审查意见、指标值或数据手册页码；
   - `[scope]`：允许改动的位号和网络，可用通配符。改需求或规则时写 `files`；
   - `[acceptance]`：门禁全过，再加上需要改善或保持的指标。
3. **只用确定性手段改**：
   - 电路代码加生成器；
   - `layout/*.toml` 配合 pcbkit 脚本；
   - 在 KiCad GUI 里手改（人做，或由人指挥 agent）；
   - 必要时对 S 表达式做最小文本修改，并在变更单里注明。
4. **过门禁**：`python3 pcbkit/gate.py`，失败就修。按变更单要求放宽阈值时，同时写 `docs/DECISIONS.md`。
5. **核对范围**：
   ```bash
   git show main:hw/<板>.kicad_pcb > /tmp/base.kicad_pcb
   python3 pcbkit/board_diff.py /tmp/base.kicad_pcb hw/<板>.kicad_pcb --scope docs/changes/NNNN-x.toml
   ```
   `out_of_scope` 必须为空，否则要么缩小改动，要么扩大变更单并说明理由。
6. **提交与 PR**：提交信息引用变更单编号。PR 描述包括：
   - 变更单要点；
   - `reports/summary.json` 摘要；
   - 指标前后值；
   - 版图对比；
   - 正反面渲染图（`kicad-cli pcb render`）；
   - 未决风险。
7. **人工审查与合并**；合并后更新 `docs/CHANGELOG.md`。

## 什么时候必须停下来问人

- 需求冲突，例如数据手册保证值低于 SPEC 的要求（示例工程里 HT7533-1 只保证 70 mA，SPEC 却写 80 mA）。
- 需要放宽门禁阈值、增加 ERC/DRC 例外或 BOM 豁免。
- 改动超出变更单范围，或要解锁已锁定的关键器件和走线。
- 安全、合规相关：电池、市电、射频发射、医疗、汽车。
- 需要花钱或对外：下单、联系厂商、推送到远端、发布。

## 回滚

一个变更一个分支，回滚就是不合并，或者 `git revert` 那个合并提交。不要在 main 上叠加修补。板子文件是 S 表达式文本，git diff 能读但不直观，审查时以 `board_diff.py` 和渲染图为准。
