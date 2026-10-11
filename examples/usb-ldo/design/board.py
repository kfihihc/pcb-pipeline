"""USB-C 3.3 V LDO demo: circuit description (SKiDL). hw/usb-ldo.kicad_sch is generated from this file;
change connectivity here, never in the schematic editor.

Run:  uv run python design/board.py      (then python3 pcbkit/gate.py)
Parts and their reasons: parts/parts.csv and docs/DECISIONS.md. Pin facts: data/parts/<MPN>/facts.toml.
"""
import os, subprocess, sys, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / 'pcb.toml').read_text(encoding='utf-8'))['project']   # title, revision
for v in ('10', '9', '8'):
    os.environ.setdefault(f'KICAD{v}_SYMBOL_DIR', '/usr/share/kicad/symbols')
    os.environ.setdefault(f'KICAD{v}_FOOTPRINT_DIR', '/usr/share/kicad/footprints')

from skidl import KICAD10, Net, Part, ERC, generate_netlist, set_default_tool  # noqa: E402

set_default_tool(KICAD10)


def part(lib, name, ref, tag, footprint, mpn, lcsc, value=None):
    """A fitted part with a stable tag (tags become symbol UUIDs, which keep the board linked)."""
    p = Part(lib, name, ref=ref, tag=tag, footprint=footprint, **({'value': value} if value else {}))
    p.fields['MPN'] = mpn
    p.fields['LCSC'] = lcsc
    p.fields.pop('SKiDL Line', None)      # source line numbers would change the schematic on every edit
    return p


def circuit():
    vbus, v3v3, gnd = Net('VBUS'), Net('+3V3'), Net('GND')
    cc1, cc2, led_a = Net('CC1'), Net('CC2'), Net('LED_A')

    # J1: USB-C power-only receptacle, default sink (D-0001, D-0003)
    j1 = part('Connector', 'USB_C_Receptacle_PowerOnly_6P', 'J1', 'usb_c',
              'Connector_USB:USB_C_Receptacle_GCT_USB4125-xx-x-0190_6P_TopMnt_Horizontal',
              'USB4125-GF-A-0190', 'C5246813', value='USB-C')
    vbus += j1['A9'], j1['B9']
    gnd += j1['A12'], j1['B12'], j1['SH']
    cc1 += j1['A5']
    cc2 += j1['B5']

    # R1, R2: 5.1 k CC pull-downs, one per CC pin (USB Type-C sink)
    r1 = part('Device', 'R', 'R1', 'r_cc1', 'Resistor_SMD:R_0603_1608Metric', '0603WAF5101T5E', 'C23186', '5.1k')
    r2 = part('Device', 'R', 'R2', 'r_cc2', 'Resistor_SMD:R_0603_1608Metric', '0603WAF5101T5E', 'C23186', '5.1k')
    cc1 += r1[1]; gnd += r1[2]
    cc2 += r2[1]; gnd += r2[2]

    # U1: HT7533-1 LDO with 10 uF in and out (datasheet p.12 basic circuit; D-0002)
    u1 = part('Regulator_Linear', 'HT75xx-1-SOT89', 'U1', 'ldo', 'Package_TO_SOT_SMD:SOT-89-3', 'HT7533-1', 'C14289', 'HT7533-1')
    c1 = part('Device', 'C', 'C1', 'c_in', 'Capacitor_SMD:C_0805_2012Metric', 'CL21A106KAYNNNE', 'C15850', '10uF 25V')
    c2 = part('Device', 'C', 'C2', 'c_out', 'Capacitor_SMD:C_0603_1608Metric', 'CL10A106KP8NNNC', 'C19702', '10uF 10V')
    vbus += u1['VIN'], c1[1]
    v3v3 += u1['VOUT'], c2[1]
    gnd += u1['GND'], c1[2], c2[2]

    # D1, R3: power LED, about 1.4 mA (R-04; simulated in sim/led_current.cir)
    r3 = part('Device', 'R', 'R3', 'r_led', 'Resistor_SMD:R_0603_1608Metric', '0603WAF1001T5E', 'C21190', '1k')
    d1 = part('Device', 'LED', 'D1', 'led', 'LED_SMD:LED_0603_1608Metric', 'KT-0603R', 'C2286', 'red')
    v3v3 += r3[1]
    led_a += r3[2], d1['A']
    gnd += d1['K']

    # J2: 1x3 header, 3V3 / GND / VBUS (R-05)
    j2 = part('Connector_Generic', 'Conn_01x03', 'J2', 'header', 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
              'PZ254V-11-03P', 'C2937625', 'Header 1x3')
    v3v3 += j2[1]; gnd += j2[2]; vbus += j2[3]



if __name__ == '__main__':
    circuit()
    ERC()
    hw = ROOT / 'hw'
    hw.mkdir(exist_ok=True)
    net = ROOT / 'design' / 'usb-ldo.net'
    generate_netlist(file_=str(net))
    # Readable label-based schematic; VBUS and GND come from J1, so they get power flags for ERC
    subprocess.run([sys.executable, str(ROOT / 'pcbkit' / 'sch_gen.py'), str(net), str(hw / 'usb-ldo.kicad_sch'),
                    '--title', PROJECT['title'], '--rev', PROJECT['revision'], '--power-flag', 'VBUS', '--power-flag', 'GND',
                    '--normalize-input',
                    ], check=True)
