"""{{title}}: circuit description (SKiDL). The schematic hw/{{name}}.kicad_sch is generated from this
file; change connectivity here, never in the schematic editor.

Run:  uv run python design/board.py      (then python3 pcbkit/gate.py)
Rules of thumb:
  - give every part a stable tag (tag="ldo"): tags become symbol UUIDs, which keep the board linked;
  - put MPN / LCSC on every fitted part (they must be registered in parts/parts.csv);
  - use KiCad library symbols and footprints whose pins match the datasheet (data/parts/<MPN>/facts.toml).
"""
import os, subprocess, sys, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / 'pcb.toml').read_text(encoding='utf-8'))['project']   # title, revision
for v in ('10', '9'):
    os.environ.setdefault(f'KICAD{v}_SYMBOL_DIR', '/usr/share/kicad/symbols')
    os.environ.setdefault(f'KICAD{v}_FOOTPRINT_DIR', '/usr/share/kicad/footprints')
os.environ.setdefault('KICAD8_SYMBOL_DIR', '/usr/share/kicad/symbols')

from skidl import KICAD10, NC, Net, Part, ERC, default_circuit, generate_netlist, set_default_tool  # noqa: E402

set_default_tool(KICAD10)


def part(lib, name, ref, tag, footprint, value=None, mpn='', lcsc='', **fields):
    p = Part(lib, name, ref=ref, tag=tag, footprint=footprint, **({'value': value} if value else {}))
    p.fields.update({'MPN': mpn, 'LCSC': lcsc, **fields})
    return p


def mark_nc(circuit_parts):
    """Record pins tied to SKiDL's NC in the part field NC_PINS: SKiDL drops them from the netlist, and
    sch_gen.py turns the field into no-connect flags. Any other open pin is reported by ERC."""
    for p in circuit_parts:
        nc = [pin.num for pin in p.pins if any(getattr(n, 'name', '') == 'NC' or n is NC for n in getattr(pin, 'nets', []))]
        if nc:
            p.fields['NC_PINS'] = ','.join(sorted(nc, key=lambda x: (len(x), x)))


def circuit():
    gnd = Net('GND')
    # --- describe the circuit here ---
    return gnd


if __name__ == '__main__':
    circuit()
    mark_nc(default_circuit.parts)
    ERC()
    net = ROOT / 'design' / '{{name}}.net'
    generate_netlist(file_=str(net))
    # readable label-based schematic (pcbkit/sch_gen.py); list connector-fed supplies with --power-flag
    subprocess.run([sys.executable, str(ROOT / 'pcbkit' / 'sch_gen.py'), str(net), str(ROOT / 'hw' / '{{name}}.kicad_sch'),
                    '--title', PROJECT['title'], '--rev', PROJECT['revision'], '--normalize-input'], check=True)
