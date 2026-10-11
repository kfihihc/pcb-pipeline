# facts.toml 格式

文件位置：`data/parts/<MPN>/facts.toml`，与 `datasheet.pdf`、`source.json` 放在一起。MPN 中的 `/` 换成 `_`。TOML 用标准库就能读（Python 3.11+ 的 tomllib）。

```toml
# 一句话说明来源：厂商、文档名、版本、日期；没有采用的版本也写上，并写明原因
[part]
mpn = "HT7533-1"
manufacturer = "Holtek"
lcsc = "C14289"
datasheet = "datasheet.pdf"
revision = "Rev. 2.30 (2014-03-19)"
sha256 = "<与 source.json 一致>"

[kicad]                                   # datasheet.py check 用它核对引脚和焊盘
symbol = "Regulator_Linear:HT75xx-1-SOT89"
footprint = "Package_TO_SOT_SMD:SOT-89-3"

[package]
name = "SOT89"
page = 2

[[pin]]                                   # 每个引脚一条；type 用 KiCad 的引脚类型
number = "2"
name = "VIN"
type = "power_in"                         # input output bidirectional tri_state passive free unspecified
page = 2                                  # power_in power_out open_collector open_emitter no_connect

[[abs_max]]                               # 绝对最大值：min 和/或 max，加 unit
param = "Supply voltage"
min = -0.3
max = 33
unit = "V"
page = 2

[[recommended]]                           # 推荐工作条件
param = "Input voltage"
max = 30
unit = "V"
page = 5

[[characteristic]]                        # 电气特性：保证值 min/max 与典型值 typ 分开写，写测试条件
param = "Output current"
min = 70
typ = 100
unit = "mA"
conditions = "VIN = 5.3 V"
page = 5
note = "guaranteed minimum is 70 mA, not the 100 mA of the title"

[[application]]                           # 典型应用电路里的外围器件
ref = "C1"
value = "10uF"
note = "input capacitor, VIN to GND"
page = 12

[[layout]]                                # 布局建议（原文要点）
text = "..."
page = 12

[[caveat]]                                # 容易出错的地方：与描述不一致、编号约定、稳定性、机械尺寸
text = "..."
page = 12
```

`datasheet.py check` 会核对以下内容：

- `[part]` 有 mpn、manufacturer、datasheet。
- `datasheet.pdf` 的 SHA-256 与 `source.json` 一致，`[part].sha256` 与两者一致。
- 每条事实都有整数页码，并在 1 到总页数之间。
- abs_max 和 recommended 至少有 min 或 max 之一；abs_max、recommended、characteristic 都有 unit。
- 引脚类型合法，引脚号不重复。
- 有 `[kicad].symbol` 时，引脚号与符号一一对应，引脚名也对得上（忽略大小写和符号；KiCad 的名字是数据手册名字的一部分也算对上）。
- 有 `[kicad].footprint` 时，数据手册的每个引脚都有对应焊盘。

引脚名对不上不一定是错，例如 KiCad 写 `VO`、数据手册写 `VOUT`，`check` 会报出来，由人判断。真的不一致时，换符号或者在 caveat 里说明。
