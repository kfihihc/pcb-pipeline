# 器件资料

每个选用的器件一个目录 `data/parts/<MPN>/`（MPN 中的 `/` 换成 `_`）：

- `datasheet.pdf`：数据手册原件（许可不允许再分发时只留 `source.json` 里的链接和 SHA-256）
- `source.json`：下载链接、日期、SHA-256、页数
- `pages/`：逐页文本（`pcb-datasheet` 技能生成，供检索；不入库也可以）
- `facts.toml`：整理出的事实，每条带页码（引脚、绝对最大值、推荐工作条件、典型应用、布局建议）
