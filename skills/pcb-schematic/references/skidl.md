# SKiDL 写法（2.3 实测，KiCad 10 库，Python 3.14）

## 骨架

模板 `design/board.py`（示例工程 `examples/usb-ldo/design/board.py` 是完整电路）：

```python
import os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for v in ('10', '9', '8'):
    os.environ.setdefault(f'KICAD{v}_SYMBOL_DIR', '/usr/share/kicad/symbols')
    os.environ.setdefault(f'KICAD{v}_FOOTPRINT_DIR', '/usr/share/kicad/footprints')
from skidl import KICAD10, Net, Part, ERC, generate_netlist, set_default_tool
set_default_tool(KICAD10)

def part(lib, name, ref, tag, footprint, mpn, lcsc, value=None):
    p = Part(lib, name, ref=ref, tag=tag, footprint=footprint, **({'value': value} if value else {}))
    p.fields['MPN'] = mpn          # p.MPN = ... 不会进入网表
    p.fields['LCSC'] = lcsc
    return p

def circuit():
    vbus, v3v3, gnd = Net('VBUS'), Net('+3V3'), Net('GND')
    u1 = part('Regulator_Linear', 'HT75xx-1-SOT89', 'U1', 'ldo', 'Package_TO_SOT_SMD:SOT-89-3', 'HT7533-1', 'C14289', 'HT7533-1')
    vbus += u1['VIN']; v3v3 += u1['VOUT']; gnd += u1['GND']      # 引脚名或引脚号都可以
    ...

if __name__ == '__main__':
    circuit(); ERC()
    net = ROOT / 'design' / 'board.net'
    generate_netlist(file_=str(net))
    subprocess.run([sys.executable, str(ROOT / 'pcbkit/sch_gen.py'), str(net), str(ROOT / 'hw/board.kicad_sch'),
                    '--title', '...', '--rev', '0.1.0', '--power-flag', 'VBUS', '--power-flag', 'GND',
                    '--normalize-input'], check=True)
```

## 模式

- **子电路**：用函数封装重复的模块（例如每路传感器一个函数），参数是网络。在函数里给 tag 加前缀，例如 `tag=f'{prefix}_r1'`，保证唯一且稳定。
- **总线**：`Bus('D', 8)` 和 `u1['D[0:7]'] += bus`，连接前先用数据手册核对引脚顺序。
- **两端器件串联**：`vin & r1 & vout & r2 & gnd` 简洁，但不直观的地方要加注释写明方向。
- **多单元器件**（四运放等）：`u1.A`、`u1.B` 按单元连接。sch_gen 会把每个单元单独摆放。
- **有意不接**：`u1['NC'] += NC`，并在生成网表前调用模板里的 `mark_nc(default_circuit.parts)`。SKiDL 会把 NC 引脚从网表里删掉，所以要用字段 `NC_PINS` 记下来，sch_gen 再据此放不连接标记（2026-10-10 实测）。
- **DNP**：`p.fields['DNP'] = 'yes'`，sch_gen 会把它标成 `(dnp yes)`。门禁对 DNP 器件不要求 BOM 字段。
- **备用方案**（二选一的电阻）：两个都画出来，一个标 DNP，并在 intent 的 `[parts] dnp` 里写明。

## 已知问题

- SKiDL 自带的 `generate_schematic()` 在稍大的电路上会 RoutingFailure，小电路的图面也很挤，所以一律用 `pcbkit/sch_gen.py`。
- SKiDL 会在当前目录写 `<脚本名>.log` 和 `.erc`，模板的 `.gitignore` 已忽略它们。
- 没有 fp-lib-table 时会提示 “Component footprints are not available”。这不影响生成网表：封装只作为字符串传给 KiCad。封装是否存在、焊盘是否匹配，由门禁 netlist 检查。
- 生成的 ERC 警告 “Insufficient drive current … POWER-IN” 是 SKiDL 自己的 ERC 给的，以 KiCad ERC（门禁 erc）为准。

## 其他代码工具

只要能输出 KiCad 网表（S 表达式或 XML），都可以接到 `sch_gen.py`：

- **tscircuit**：用 `circuit-json-to-kicad` 转换（本机有 Node 24）；
- **atopile**：公开仓库自 2026-03 起基本停更，慎用；
- **项目自写生成器**：S3 的 `gen/build.py` 直接写 `.kicad_sch`，同样纳入 reproduce 检查。

接入方法：在 `pcb.toml` 的 `[design].generate` 里写生成命令。
