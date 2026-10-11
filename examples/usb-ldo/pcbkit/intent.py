"""Connectivity intent: assertions about the schematic's netlist, written independently of the
schematic or the design code (design/intent.toml). They are the functional checks a reviewer would
otherwise trace by hand, e.g. "GPIO1 drives LCD reset" or "battery minus is not tied to ground".

  [[connect]]                       # the pins share one net (optionally with this name)
  name = "LDO input from VBUS"
  pins = ["J1.A9", "U1.3"]
  net = "VBUS"

  [[isolate]]                       # no two of these pins share a net
  name = "Battery minus stays off GND"
  pins = ["J2.2", "U1.4"]

  [[net]]                           # the net has exactly these members
  name = "+3V3"
  pins = ["U1.2", "C2.1", "R3.1"]

  [parts]
  required = ["U1", "J1"]           # must exist (and be fitted unless listed in dnp)
  dnp = ["R9"]                      # must exist and be marked DNP
  absent = ["R10"]                  # must not exist

usage: python3 pcbkit/intent.py netlist.xml design/intent.toml
"""
import sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import parse_netlist, pin_to_net  # noqa: E402


def _pin(spec):
    ref, _, num = spec.partition('.')
    return ref, num


def check(netlist, intent):
    by_pin = pin_to_net(netlist)
    comps = netlist['components']
    problems = []

    def where(spec):
        p = _pin(spec)
        if p[0] not in comps:
            problems.append(f'intent: unknown part {p[0]} ({spec})'); return None
        return by_pin.get(p, f'<unconnected {spec}>')

    for c in intent.get('connect', []):
        nets = {s: where(s) for s in c['pins']}
        if None in nets.values():
            continue
        if len(set(nets.values())) != 1:
            problems.append(f"connect '{c['name']}': pins on different nets {nets}")
        elif c.get('net') and next(iter(nets.values())) != c['net']:
            problems.append(f"connect '{c['name']}': net is {next(iter(nets.values()))}, expected {c['net']}")
    for c in intent.get('isolate', []):
        nets = {s: where(s) for s in c['pins']}
        if None in nets.values():
            continue
        seen = {}
        for s, n in nets.items():
            if n in seen and not n.startswith('<unconnected'):
                problems.append(f"isolate '{c['name']}': {seen[n]} and {s} share net {n}")
            seen.setdefault(n, s)
    for c in intent.get('net', []):
        got = {f'{r}.{p}' for r, p in netlist['nets'].get(c['name'], [])}
        want = set(c['pins'])
        if got != want:
            problems.append(f"net '{c['name']}': missing {sorted(want - got)}, unexpected {sorted(got - want)}")
    parts = intent.get('parts', {})
    for ref in parts.get('required', []):
        if ref not in comps:
            problems.append(f'parts: {ref} is required but missing')
        elif comps[ref]['dnp'] and ref not in parts.get('dnp', []):
            problems.append(f'parts: {ref} is required but marked DNP')
    for ref in parts.get('dnp', []):
        if ref not in comps or not comps[ref]['dnp']:
            problems.append(f'parts: {ref} must exist and be DNP')
    for ref in parts.get('absent', []):
        if ref in comps:
            problems.append(f'parts: {ref} must not exist')
    return problems


if __name__ == '__main__':
    n = parse_netlist(sys.argv[1])
    probs = check(n, tomllib.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
    print('\n'.join(probs) or 'intent OK')
    sys.exit(1 if probs else 0)
