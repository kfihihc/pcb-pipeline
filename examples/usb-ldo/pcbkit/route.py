"""Route the board as a transaction: the router works on a scratch copy, the candidate is refilled and
checked with KiCad's DRC under the project's own rules, and only a candidate that passes replaces the
board. The project file is never taken from the router (KiCadRoutingTools would lower DRC minimums to
whatever it produced).

Settings: layout/route.toml
  router = "krt"                          # KiCadRoutingTools (MIT); see the pcb-layout skill for setup
  krt = "~/.cache/pcb-pipeline/KiCadRoutingTools-v0.22.1"
  nets = ["*"]
  track_width = 0.25
  clearance = 0.2
  via_size = 0.6
  via_drill = 0.3
  board_edge_clearance = 0.3
  power_nets = { VBUS = 0.5, "+3V3" = 0.4 }     # net (pattern) -> width, mm
  net_clearances = { VBUS = 0.3 }              # mirror per-net clearances of custom .kicad_dru rules here
  extra_args = []

Accepted when the candidate has no DRC violations and no unconnected items (--allow-unconnected,
--allow-violations to adopt a partial result on purpose). Locked tracks and footprints are obstacles.

usage: python3 pcbkit/route.py [--config pcb.toml] [--settings layout/route.toml] [--dry-run]
Output: work/route-<time>/ (router log, candidate, DRC report) and a JSON summary.
"""
import argparse, datetime, json, os, shutil, subprocess, sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def drc(board, out):
    common.kicad_cli('pcb', 'drc', '--refill-zones', '--save-board', '--format', 'json', '--severity-all', '-o', out, board)
    d = json.loads(Path(out).read_text())
    return {'violations': len(d.get('violations', [])), 'unconnected': len(d.get('unconnected_items', [])),
            'types': sorted({v['type'] for v in d.get('violations', [])})}


def main():
    ap = argparse.ArgumentParser(description='Route on a scratch copy; adopt only a candidate that passes DRC')
    ap.add_argument('--config'); ap.add_argument('--settings', default='layout/route.toml')
    ap.add_argument('--allow-unconnected', action='store_true'); ap.add_argument('--allow-violations', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='route and check, but keep the current board')
    a = ap.parse_args()
    p = common.Project(a.config)
    cfg = tomllib.loads((p.root / a.settings).read_text(encoding='utf-8'))
    if cfg.get('router', 'krt') != 'krt':
        sys.exit('only router = "krt" is wired up; run other routers by hand on a copy and check with the gate')
    krt = Path(os.path.expanduser(cfg.get('krt', '~/.cache/pcb-pipeline/KiCadRoutingTools-v0.22.1')))
    py = krt / '.venv/bin/python'
    if not py.exists():
        sys.exit(f'{krt} is not set up: run the pcb-layout skill script setup_krt.sh')
    work = p.root / 'work' / ('route-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    work.mkdir(parents=True)
    stem = p.pcb.stem
    for f in (p.pcb, p.pro, p.dru, p.kicad_dir / 'fp-lib-table', p.kicad_dir / 'sym-lib-table'):
        if f and f.exists():
            shutil.copy(f, work / f.name)
    before = drc(work / p.pcb.name, work / 'drc-before.json')
    shutil.copy(p.pcb, work / p.pcb.name)          # drc() saved a refilled copy; route the committed board
    out = work / f'{stem}-routed.kicad_pcb'
    args = [str(py), str(krt / 'py_router/route.py'), str(work / p.pcb.name), str(out), '--nets', *cfg.get('nets', ['*'])]
    for key, flag in (('track_width', '--track-width'), ('clearance', '--clearance'), ('via_size', '--via-size'),
                      ('via_drill', '--via-drill'), ('board_edge_clearance', '--board-edge-clearance')):
        if key in cfg:
            args += [flag, str(cfg[key])]
    if cfg.get('power_nets'):
        args += ['--power-nets', *cfg['power_nets'].keys(), '--power-nets-widths', *map(str, cfg['power_nets'].values())]
    if cfg.get('net_clearances'):
        (work / 'net-clearances.json').write_text(json.dumps(cfg['net_clearances']))
        args += ['--net-clearances', str(work / 'net-clearances.json')]
    args += ['--no-fix-drc-settings', *cfg.get('extra_args', [])]
    r = subprocess.run(args, cwd=p.root, capture_output=True, text=True)
    (work / 'router.log').write_text(r.stdout + r.stderr)
    summary = {'work': p.rel(work), 'router_exit': r.returncode, 'before': before}
    if r.returncode or not out.exists():
        summary['result'] = 'router failed, board unchanged (see router.log)'
        print(json.dumps(summary, indent=1)); return 1
    for f in (p.pro, p.dru):                       # the project's rules, not the router's
        if f and f.exists():
            shutil.copy(f, out.with_suffix(f.suffix))
    after = drc(out, work / 'drc-candidate.json')
    summary['candidate'] = after
    ok = (after['violations'] == 0 or a.allow_violations) and (after['unconnected'] == 0 or a.allow_unconnected)
    if ok and not a.dry_run:
        shutil.copy(out, p.pcb)
        summary['result'] = f'adopted: {p.rel(p.pcb)} replaced by the checked candidate'
    else:
        summary['result'] = ('dry run: ' if a.dry_run else 'rejected: ') + f"{after['violations']} violations, {after['unconnected']} unconnected; board unchanged"
    print(json.dumps(summary, indent=1))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
