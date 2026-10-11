"""Official reference designs as data: export their connectivity, cut out the circuit around one IC, and
compare it pin by pin with ours.

  refnet.py export SRC --out refs/<name>/netlist.json
        SRC: .kicad_sch / .kicad_pro / .kicad_pcb, a directory or .zip holding a KiCad project, or a board in
        another format that `kicad-cli pcb import` reads (Altium .PcbDoc, EAGLE .brd, PADS, CADSTAR, ...)
  refnet.py around netlist.json U1 [--depth 1] [--stop "GND*,+*,VCC*,VDD*,3V3*"] [--json out.json]
        every pin of the anchor: its net and what else sits on it (value, footprint); --depth 2 follows the
        passives one more step (e.g. the far side of a crystal load capacitor)
  refnet.py compare REF.json OURS.json --anchor U3=U1 [--map C12=C4,...] [--stop ...]
        pin-by-pin comparison around the anchor: same / different connection, part values side by side;
        parts on each anchor pin are matched automatically by type and pin, explicit --map overrides

PDF-only reference designs: transcribe the circuit around the IC into the same JSON format by hand from the
rendered pages (pcb-datasheet `render`), with the page number per net, then use `around` and `compare`.
JSON: {"source": ..., "components": {ref: {"value", "footprint", "lib_id"}}, "nets": {name: [[ref, pin], ...]}}
"""
import argparse, fnmatch, hashlib, json, re, shutil, subprocess, sys, tempfile, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

STOP = 'GND,GND*,*GND,AGND*,DGND*,+*,-*,VCC*,VDD*,VSS*,3V3*,*3V3,1V1*,5V*,VBUS*,VSYS*,VBAT*'


def kicad_cli(*args, cwd=None):
    r = subprocess.run(['kicad-cli', *map(str, args)], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('kicad-cli %s failed: %s' % (' '.join(map(str, args[:3])), (r.stdout + r.stderr)[-500:]))
    return r


def from_xml(path):
    x = ET.parse(path).getroot()
    comps = {}
    for c in x.find('components'):
        ref = c.get('ref')
        if ref.startswith('#'):
            continue
        src = c.find('libsource')
        comps[ref] = {'value': c.findtext('value') or '', 'footprint': c.findtext('footprint') or '',
                      'lib_id': f"{src.get('lib')}:{src.get('part')}" if src is not None else ''}
    pinnames = {}
    for lp in x.find('libparts') if x.find('libparts') is not None else []:
        pinnames[(lp.get('lib'), lp.get('part'))] = {p.get('num'): p.get('name') for p in lp.iter('pin')}
    nets = {}
    names = {}
    for n in x.find('nets'):
        members = []
        for m in n.findall('node'):
            if m.get('ref', '').startswith('#'):
                continue
            members.append([m.get('ref'), m.get('pin')])
            if m.get('pinfunction'):
                names[f"{m.get('ref')}.{m.get('pin')}"] = m.get('pinfunction')
        if members:
            nets[n.get('name')] = members
    return comps, nets, names


def from_board(path):
    sys.path.append('/usr/lib/python3/dist-packages')
    import pcbnew
    b = pcbnew.LoadBoard(str(path))
    comps, nets = {}, {}
    for f in b.GetFootprints():
        ref = f.GetReference()
        comps[ref] = {'value': f.GetValue(), 'footprint': f.GetFPID().GetUniStringLibId(), 'lib_id': ''}
        for p in f.Pads():
            if p.GetNetname() and p.GetNumber():
                nets.setdefault(p.GetNetname(), [])
                if [ref, p.GetNumber()] not in nets[p.GetNetname()]:
                    nets[p.GetNetname()].append([ref, p.GetNumber()])
    return comps, nets, {}


def export(src, out):
    src = Path(src).resolve()
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        root = src
        if src.suffix == '.zip':
            with zipfile.ZipFile(src) as z:
                z.extractall(d / 'zip')
            root = d / 'zip'
        if root.is_dir():
            pros = sorted(root.rglob('*.kicad_pro'))
            schs = [p.with_suffix('.kicad_sch') for p in pros if p.with_suffix('.kicad_sch').exists()] or sorted(root.rglob('*.kicad_sch'))
            pcbs = [p.with_suffix('.kicad_pcb') for p in pros if p.with_suffix('.kicad_pcb').exists()] or sorted(root.rglob('*.kicad_pcb'))
            target = schs[0] if schs else (pcbs[0] if pcbs else None)
            if target is None:
                raise SystemExit(f'no KiCad schematic or board in {src}')
        else:
            target = root.with_suffix('.kicad_sch') if root.suffix == '.kicad_pro' else root
        if target.suffix == '.kicad_sch':
            xml = d / 'n.xml'
            kicad_cli('sch', 'export', 'netlist', '--format', 'kicadxml', '-o', xml, target)
            comps, nets, names = from_xml(xml)
            kind = 'schematic'
        elif target.suffix == '.kicad_pcb':
            comps, nets, names = from_board(target)
            kind = 'board'
        else:
            imported = d / 'imported.kicad_pcb'
            kicad_cli('pcb', 'import', '-o', imported, target)
            comps, nets, names = from_board(imported)
            kind = f'board imported from {target.suffix}'
    data = {'source': str(src), 'file': target.name, 'kind': kind, 'sha256': hashlib.sha256(src.read_bytes()).hexdigest() if src.is_file() else None,
            'components': comps, 'nets': nets, 'pin_names': names}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')
    print(f'{out}: {len(comps)} parts, {len(nets)} nets from {target.name} ({kind})')


def load(path):
    d = json.loads(Path(path).read_text())
    by_pin = {(r, p): n for n, ms in d['nets'].items() for r, p in ms}
    return d, by_pin


def is_stop(net, stop):
    return any(fnmatch.fnmatchcase(net.upper(), s.upper()) for s in stop)


def around(path, anchor, depth, stop):
    d, by_pin = load(path)
    comps, names = d['components'], d.get('pin_names', {})
    pins = sorted({p for (r, p) in by_pin if r == anchor}, key=lambda x: (len(x), x))
    if not pins:
        raise SystemExit(f'{anchor} not found')
    rows, seen = [], {anchor}
    frontier = []
    for pin in pins:
        net = by_pin[(anchor, pin)]
        others = [(r, p) for r, p in d['nets'][net] if r != anchor]
        rows.append({'pin': pin, 'name': names.get(f'{anchor}.{pin}', ''), 'net': net, 'stop': is_stop(net, stop),
                     'others': [{'ref': r, 'pin': p, 'value': comps.get(r, {}).get('value', ''), 'footprint': comps.get(r, {}).get('footprint', '')}
                                for r, p in others][:12 if is_stop(net, stop) else 50]})
        if not is_stop(net, stop):
            frontier += [r for r, _ in others]
    second = []
    if depth > 1:
        for r in sorted(set(frontier) - seen):
            for (rr, p), net in by_pin.items():
                if rr == r and not any(net == row['net'] for row in rows):
                    second.append({'via': r, 'pin': p, 'net': net, 'members': [f'{a}.{b}' for a, b in d['nets'][net] if a != r][:12]})
    return {'anchor': anchor, 'value': comps.get(anchor, {}).get('value'), 'source': d.get('source'), 'pins': rows, 'second': second}


def compare(ref_path, ours_path, anchor_map, explicit, stop):
    ra, oa = anchor_map
    R = around(ref_path, ra, 1, stop)
    O = around(ours_path, oa, 1, stop)
    rpins = {x['pin']: x for x in R['pins']}
    opins = {x['pin']: x for x in O['pins']}
    mapping = dict(explicit)
    # auto-map: parts of the same type (reference prefix) on the same anchor pin
    for pin, r in rpins.items():            # evidence from signal pins only: supply nets hold dozens of capacitors
        o = opins.get(pin)
        if not o or r['stop'] or o['stop']:
            continue
        for a in r['others']:
            if a['ref'] in mapping:
                continue
            free = [b for b in o['others'] if b['ref'] not in mapping.values()]
            kind = lambda ref: re.sub(r'\d+$', '', ref)
            for test in (lambda b: b['ref'] == a['ref'] and b['pin'] == a['pin'],            # same name, same pin
                         lambda b: kind(b['ref']) == kind(a['ref']) and b['value'] == a['value'] and b['pin'] == a['pin'],
                         lambda b: kind(b['ref']) == kind(a['ref'])):
                cand = [b for b in free if test(b)]
                if len(cand) == 1:
                    mapping[a['ref']] = cand[0]['ref']
                    break
    out = []
    for pin in sorted(set(rpins) | set(opins), key=lambda x: (len(x), x)):
        r, o = rpins.get(pin), opins.get(pin)
        if not r or not o:
            out.append({'pin': pin, 'status': 'missing in ours' if r else 'only in ours', 'ref': r and r['net'], 'ours': o and o['net']})
            continue
        if r['stop'] or o['stop']:
            status = 'same supply class' if r['stop'] == o['stop'] else 'supply vs signal'
            out.append({'pin': pin, 'name': r['name'] or o['name'], 'status': status, 'ref': r['net'], 'ours': o['net']}); continue
        rs = {(mapping.get(a['ref'], '?' + a['ref']), a['pin']) for a in r['others']}
        os_ = {(b['ref'], b['pin']) for b in o['others']}
        values = [(a['ref'], a['value'], mapping.get(a['ref']), next((b['value'] for b in o['others'] if b['ref'] == mapping.get(a['ref'])), None)) for a in r['others']]
        diff_vals = [v for v in values if v[2] and v[1] != v[3]]
        status = 'same' if rs == os_ and not diff_vals else ('values differ' if rs == os_ else 'connections differ')
        out.append({'pin': pin, 'name': r['name'] or o['name'], 'status': status, 'ref': r['net'], 'ours': o['net'],
                    'ref_parts': sorted(f'{a}.{b}' for a, b in rs), 'our_parts': sorted(f'{a}.{b}' for a, b in os_),
                    'values': [f'{a} {va} -> {b} {vb}' for a, va, b, vb in diff_vals]})
    return {'anchor': f'{ra} -> {oa}', 'mapping': mapping, 'pins': out,
            'summary': {s: sum(1 for x in out if x['status'] == s) for s in sorted({x['status'] for x in out})}}


def main():
    ap = argparse.ArgumentParser(description='Reference designs as data')
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export'); e.add_argument('src'); e.add_argument('--out', required=True)
    a = sub.add_parser('around'); a.add_argument('netlist'); a.add_argument('anchor'); a.add_argument('--depth', type=int, default=1)
    a.add_argument('--stop', default=STOP); a.add_argument('--json')
    c = sub.add_parser('compare'); c.add_argument('ref'); c.add_argument('ours'); c.add_argument('--anchor', required=True)
    c.add_argument('--map', default=''); c.add_argument('--stop', default=STOP); c.add_argument('--json')
    args = ap.parse_args()
    if args.cmd == 'export':
        return export(args.src, args.out)
    stop = args.stop.split(',')
    if args.cmd == 'around':
        res = around(args.netlist, args.anchor, args.depth, stop)
        if args.json:
            Path(args.json).write_text(json.dumps(res, indent=1, ensure_ascii=False) + '\n')
        print(f"{res['anchor']} {res['value']}  ({res['source']})")
        for row in res['pins']:
            parts = ', '.join(f"{o['ref']}.{o['pin']} {o['value']}" for o in row['others'])
            print(f"  {row['pin']:>4} {row['name'][:14]:14} {row['net'][:22]:22} {'[supply] ' if row['stop'] else ''}{parts[:120]}")
        for s in res['second']:
            print(f"    via {s['via']}.{s['pin']}: {s['net']} -> {', '.join(s['members'])}")
        return
    ra, _, oa = args.anchor.partition('=')
    explicit = dict(x.split('=') for x in args.map.split(',') if '=' in x)
    res = compare(args.ref, args.ours, (ra, oa), explicit, stop)
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1, ensure_ascii=False) + '\n')
    print(f"{res['anchor']}: {res['summary']}  mapping {res['mapping']}")
    for row in res['pins']:
        if row['status'] not in ('same', 'same supply class'):
            print(f"  {row['pin']:>4} {row.get('name', '')[:12]:12} {row['status']:18} ref {row['ref']}  ours {row['ours']}  "
                  f"{row.get('ref_parts', '')} {row.get('our_parts', '')} {row.get('values', '')}")


if __name__ == '__main__':
    main()
