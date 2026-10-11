"""SPICE benches with corners and assertions, run on ngspice (the libngspice shared library that KiCad
already depends on, or the ngspice program when installed).

A bench is a plain SPICE deck (it must run on its own in ngspice) plus a [[bench]] entry in
sim/benches.toml:

  [[bench]]
  id = "usb_hotplug"
  title = "USB hot-plug overshoot at the LDO input"
  deck = "usb_hotplug.cir"                 # relative to benches.toml
  params = { L_CABLE = "1u", C_IN = "10u" } # written as .param lines (same-name .param lines in the deck are replaced)
  measures = ["tran vin_peak MAX v(vin)"]   # ngspice .meas statements without the leading ".meas"
  export = ["v(vin)"]                       # optional: vectors written to reports/sim/<id>-<corner>.csv

  [[bench.corner]]                          # parameter overrides; the nominal corner is always run
  name = "derated"
  C_IN = "4u"
  why = "10 uF/10 V 0603 X5R keeps about 40 % at 5 V bias (manufacturer DC-bias curve)"

  [[bench.assert]]
  measure = "vin_peak"
  max = 6.0                                 # min / max, checked in every corner
  why = "XC6206P332MR VIN absolute maximum 6.0 V (datasheet p.2)"

usage: python3 pcbkit/sim.py sim/benches.toml [--only id] [--engine auto|lib|cli] [--out reports/sim]
"""
import argparse, ctypes, json, re, shutil, subprocess, sys, tempfile, tomllib
from pathlib import Path

MEAS = re.compile(r'^\s*([A-Za-z_][\w.]*)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)')


def build_deck(text, params, measures):
    lines = text.splitlines()
    names = {k.lower() for k in params}
    keep = [lines[0]]  # SPICE: the first line is the title
    for ln in lines[1:]:
        if re.match(r'^\s*\.param\s', ln, re.I):      # drop only the overridden names of a multi-name .param
            pairs = re.findall(r"(\w+)\s*=\s*(\{[^}]*\}|'[^']*'|[^\s=]+)", ln.split(None, 1)[1] if len(ln.split(None, 1)) > 1 else '')
            rest = [f'{n}={v}' for n, v in pairs if n.lower() not in names]
            if rest:
                keep.append('.param ' + ' '.join(rest))
            continue
        keep.append(ln)
    body = [f'.param {k}={v}' for k, v in params.items()]
    end = next((i for i in range(len(keep) - 1, 0, -1) if keep[i].strip().lower() == '.end'), len(keep))
    meas = [f'.meas {m}' for m in measures]
    return '\n'.join(keep[:1] + body + keep[1:end] + meas + ['.end']) + '\n'


def run_lib(deck_text, export, csv_path):
    lib = ctypes.CDLL('libngspice.so.0')
    out = []
    SendChar = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
    SendStat = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
    Exit = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
    cb = (SendChar(lambda s, i, p: out.append(s.decode(errors='replace')) or 0),
          SendStat(lambda s, i, p: 0), Exit(lambda *a: 0))
    lib.ngSpice_Init(cb[0], cb[1], cb[2], None, None, None, None)
    lines = deck_text.splitlines()
    arr = (ctypes.c_char_p * (len(lines) + 1))(*[l.encode() for l in lines], None)
    lib.ngSpice_Circ(arr)
    lib.ngSpice_Command(b'run')
    if export and csv_path:
        lib.ngSpice_Command(f'wrdata {csv_path} {" ".join(export)}'.encode())
    return [re.sub(r'^(stdout|stderr) ', '', l) for l in out]


def run_cli(deck_text, export, csv_path):
    with tempfile.TemporaryDirectory() as d:
        deck = Path(d) / 'deck.cir'
        if export and csv_path:   # batch mode runs .control blocks
            deck_text = deck_text.replace('\n.end\n', f'\n.control\nrun\nwrdata {csv_path} {" ".join(export)}\n.endc\n.end\n')
        deck.write_text(deck_text)
        r = subprocess.run(['ngspice', '-b', str(deck)], capture_output=True, text=True)
        return (r.stdout + r.stderr).splitlines()


def one(deck_text, engine, export, csv_path):
    """Run one deck in this process; return (measures, log)."""
    log = (run_lib if engine == 'lib' else run_cli)(deck_text, export, csv_path)
    res = {}
    for ln in log:
        m = MEAS.match(ln)
        if m and not ln.lstrip().startswith(('.', '*')):
            res.setdefault(m.group(1).lower(), float(m.group(2)))
    return res, log


def run_corner(deck_text, engine, export, csv_path):
    """Each corner in a fresh process: libngspice keeps global state between circuits."""
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'deck.cir').write_text(deck_text)
        r = subprocess.run([sys.executable, __file__, '--_one', str(Path(d, 'deck.cir')), '--engine', engine,
                            '--_csv', csv_path or '', '--_export', ' '.join(export or [])],
                           capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise RuntimeError(r.stderr.strip()[-500:] or 'simulation process failed')
        return json.loads(r.stdout.splitlines()[-1])


def pick_engine(engine):
    if engine != 'auto':
        return engine
    if shutil.which('ngspice'):
        return 'cli'
    try:
        ctypes.CDLL('libngspice.so.0'); return 'lib'
    except OSError:
        raise SystemExit('ngspice not found: install the ngspice package (or libngspice0, a KiCad dependency)')


def run_all(benches_file, only=None, engine='auto', out=None):
    benches_file = Path(benches_file)
    cfg = tomllib.loads(benches_file.read_text(encoding='utf-8'))
    engine = pick_engine(engine)
    out = Path(out) if out else None
    results = {'engine': engine, 'benches': []}
    for b in cfg.get('bench', []):
        if only and b['id'] not in only:
            continue
        text = (benches_file.parent / b['deck']).read_text(encoding='utf-8')
        corners = [{'name': 'nominal'}] + [c for c in b.get('corner', []) if c.get('name') != 'nominal']
        rec = {'id': b['id'], 'title': b.get('title', ''), 'corners': {}, 'failures': [], 'worst': {}}
        for c in corners:
            params = dict(b.get('params', {}))
            params.update({k: v for k, v in c.items() if k not in ('name', 'why')})
            deck = build_deck(text, params, b.get('measures', []))
            csv_path = None
            if out and b.get('export'):
                out.mkdir(parents=True, exist_ok=True)
                csv_path = str((out / f"{b['id']}-{c['name']}.csv").resolve())
            try:
                meas = run_corner(deck, engine, b.get('export'), csv_path)
            except Exception as e:
                rec['failures'].append((c['name'], f'{type(e).__name__}: {e}')); continue
            rec['corners'][c['name']] = {'params': params, 'measures': meas}
            for a in b.get('assert', []):
                v = meas.get(a['measure'].lower())
                if v is None:
                    rec['failures'].append((c['name'], f"{a['measure']} not measured (check the .meas statement)")); continue
                if 'max' in a and v > a['max']:
                    rec['failures'].append((c['name'], f"{a['measure']} = {v:.4g} > {a['max']} ({a.get('why', '')})"))
                if 'min' in a and v < a['min']:
                    rec['failures'].append((c['name'], f"{a['measure']} = {v:.4g} < {a['min']} ({a.get('why', '')})"))
                w = rec['worst'].get(a['measure'])
                worse = (w is None) or ('max' in a and v > w[1]) or ('min' in a and 'max' not in a and v < w[1])
                if worse:
                    rec['worst'][a['measure']] = (c['name'], v)
        results['benches'].append(rec)
    return results


def main():
    ap = argparse.ArgumentParser(description='Run SPICE benches with corners and assertions')
    ap.add_argument('benches', nargs='?'); ap.add_argument('--only', default='')
    ap.add_argument('--engine', default='auto', choices=['auto', 'lib', 'cli']); ap.add_argument('--out', default='reports/sim')
    ap.add_argument('--json'); ap.add_argument('--_one'); ap.add_argument('--_csv', default=''); ap.add_argument('--_export', default='')
    a = ap.parse_args()
    if a._one:
        meas, log = one(Path(a._one).read_text(), a.engine, a._export.split() or None, a._csv or None)
        errors = [l for l in log if re.search(r'\berror\b|failed', l, re.I) and 'warning' not in l.lower()]
        if errors and not meas:
            print('\n'.join(errors[-8:]), file=sys.stderr); sys.exit(2)
        print(json.dumps(meas)); return 0
    res = run_all(a.benches, [o for o in a.only.split(',') if o], a.engine, a.out)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, ensure_ascii=False) + '\n')
    for b in res['benches']:
        print(f"{'FAIL' if b['failures'] else 'PASS'}  {b['id']}  {b['title']}")
        for name, c in b['corners'].items():
            print(f"      {name:12} " + '  '.join(f'{k}={v:.4g}' for k, v in c['measures'].items()))
        for corner, msg in b['failures']:
            print(f'      ! {corner}: {msg}')
    return 1 if any(b['failures'] for b in res['benches']) else 0


if __name__ == '__main__':
    sys.exit(main())
