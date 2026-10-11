"""Merge gate for a KiCad board project, run locally and in CI. Exit status 1 if any check fails.

Checks (each runs when the project has what it needs; configuration in pcb.toml):

  erc        ERC: no errors; warnings only those listed in [gate].erc_allowed (each with a why)
  drc        DRC with schematic parity: no violations of any severity, no unconnected items
             (unconnected items are tolerated while [gate].allow_unrouted = true, e.g. before routing)
  rules      the custom rules file is really loaded: KiCad silently drops the whole .kicad_dru when one
             rule is malformed, so a canary rule is appended in a scratch copy and must fire
  zones      zone fills are up to date: a fresh KiCad refill in a scratch copy reproduces the saved copper
  netlist    connectivity intent ([design].intent), symbol pins vs footprint pads, BOM fields ([bom])
  metrics    layout metrics within thresholds ([gate].metrics, see metrics.py)
  sim        SPICE benches pass their assertions ([gate].sim, see sim.py)
  reproduce  generators ([design].generate) rerun in a scratch copy change no committed file

usage: python3 pcbkit/gate.py [--config pcb.toml] [--out reports] [--only a,b] [--skip a,b]
"""
import argparse, fnmatch, json, os, shutil, subprocess, sys, tempfile, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import Project, kicad_cli, write_json  # noqa: E402

CANARY = ('\n(rule "__pcbkit_canary__"\n  (condition "A.Type == \'Footprint\'")\n'
          '  (constraint assertion "A.Type != \'Footprint\'"))\n')


class Gate:
    def __init__(self, project, out):
        self.p, self.out, self.results = project, out, []
        self.g = project.section('gate')
        self._netlist = None

    def report(self, name, ok, detail='', skipped=False):
        status = 'SKIP' if skipped else ('PASS' if ok else 'FAIL')
        self.results.append({'check': name, 'status': status, 'ok': bool(ok) or skipped, 'detail': detail})
        print(f'{status:5} {name}' + (f'  ({detail})' if detail else ''), flush=True)

    # ------------------------------------------------------------ ERC / DRC
    def missing(self, name, path, hint):
        if path and not path.exists():
            self.report(name, False, f'{self.p.rel(path)} does not exist yet ({hint})')
            return True
        return False

    def erc(self):
        if not self.p.sch:
            return self.report('erc', True, 'no schematic in pcb.toml', skipped=True)
        if self.missing('erc', self.p.sch, 'generate or draw the schematic first'):
            return
        out = self.out / 'erc.json'
        kicad_cli('sch', 'erc', '--format', 'json', '--severity-all', '-o', out, self.p.sch, cwd=self.p.root)
        found = [(v['type'], v['severity'], sorted(i['description'] for i in v.get('items', [])))
                 for s in json.loads(out.read_text())['sheets'] for v in s.get('violations', [])]
        allowed = [(a['type'], sorted(a.get('items', []))) for a in self.g.get('erc_allowed', [])]
        errors = [f for f in found if f[1] == 'error' and (f[0], f[2]) not in allowed]
        unexpected = [f for f in found if f[1] != 'error' and (f[0], f[2]) not in allowed]
        self.report('erc', not errors and not unexpected,
                    f'{len(errors)} errors, {len(unexpected)} unlisted warnings, {len(found)} total'
                    + ''.join(f'; {t}: {", ".join(i)}' for t, _, i in (errors + unexpected)[:6]))

    def drc(self):
        if not self.p.pcb:
            return self.report('drc', True, 'no board in pcb.toml', skipped=True)
        if self.missing('drc', self.p.pcb, 'create it with pcbkit/board_setup.py'):
            return
        out = self.out / 'drc.json'
        parity = ['--schematic-parity'] if self.p.sch and self.p.sch.exists() else []
        kicad_cli('pcb', 'drc', '--format', 'json', '--severity-all', *parity, '-o', out, self.p.pcb, cwd=self.p.root)
        d = json.loads(out.read_text())
        allowed = [(a['type'], a.get('contains', '')) for a in self.g.get('drc_allowed', [])]
        def listed(v): return any(v['type'] == t and c in v['description'] for t, c in allowed)
        groups = {g: [v for v in d.get(g, []) if not listed(v)] for g in ('violations', 'unconnected_items', 'schematic_parity')}
        failing = dict(groups)
        if self.g.get('allow_unrouted'):
            failing['unconnected_items'] = []
        ok = not any(failing.values())
        self.report('drc', ok, ', '.join(f'{len(v)} {g}' for g, v in groups.items())
                    + (' (unrouted allowed)' if self.g.get('allow_unrouted') else '')
                    + ''.join(f'; {v["type"]}: {v["description"]}' for g in failing.values() for v in g[:4]))

    def rules(self):
        if not (self.p.dru and self.p.dru.exists() and self.p.pcb.exists()):
            return self.report('rules', True, 'no custom rules file', skipped=True)
        with tempfile.TemporaryDirectory() as d:
            for f in (self.p.pcb, self.p.pro, self.p.dru):
                if f and f.exists():
                    shutil.copy(f, d)
            dru = Path(d) / self.p.dru.name
            dru.write_text(dru.read_text(encoding='utf-8') + CANARY, encoding='utf-8')
            kicad_cli('pcb', 'drc', '--format', 'json', '--severity-all', '-o', Path(d) / 'drc.json', Path(d) / self.p.pcb.name)
            hits = [v for v in json.loads((Path(d) / 'drc.json').read_text())['violations'] if '__pcbkit_canary__' in v['description']]
        n_rules = self.p.dru.read_text(encoding='utf-8').count('(rule ')
        self.report('rules', bool(hits), f'{n_rules} custom rules loaded (canary fired {len(hits)}x)' if hits else
                    f'{self.p.dru.name} is NOT loaded: KiCad dropped the whole file because of a syntax or constraint '
                    'error; check it in the board editor (File > Board Setup > Custom Rules > Check rule syntax)')

    # ------------------------------------------------------------ zones
    def zones(self):
        if not self.p.pcb or not self.p.pcb.exists():
            return self.report('zones', True, 'no board', skipped=True)
        import kicad_compat as kc
        k = kc.pcbnew

        def areas(path):
            b = k.LoadBoard(str(path))
            return {(z.GetZoneName() or z.GetNetname(), k.LayerName(l)): z.GetFilledPolysList(l).Area() / 1e12
                    for z in b.Zones() for l in z.GetLayerSet().Seq() if not z.GetIsRuleArea() and z.HasFilledPolysForLayer(l)}
        saved = areas(self.p.pcb)
        if not saved:
            return self.report('zones', True, 'no filled zones', skipped=True)
        with tempfile.TemporaryDirectory() as d:
            for f in (self.p.pcb, self.p.pro, self.p.dru):
                if f and f.exists():
                    shutil.copy(f, d)
            kicad_cli('pcb', 'drc', '--refill-zones', '--save-board', '--format', 'json', '-o', Path(d) / 'drc.json', Path(d) / self.p.pcb.name)
            fresh = areas(Path(d) / self.p.pcb.name)
        diff = {f'{n} {l}': abs(saved.get((n, l), 0) - fresh.get((n, l), 0)) for n, l in set(saved) | set(fresh)}
        worst = max(diff, key=diff.get)
        tol = self.g.get('zone_fill_tolerance_mm2', 0.01)
        self.report('zones', diff[worst] <= tol, f'largest change after refill {diff[worst]:.4f} mm2 ({worst}); '
                    'refill with: kicad-cli pcb drc --refill-zones --save-board <board>')

    # ------------------------------------------------------------ netlist: intent, pins/pads, BOM fields
    def netlist(self):
        if not self.p.sch:
            return self.report('netlist', True, 'no schematic', skipped=True)
        if self.missing('netlist', self.p.sch, 'generate or draw the schematic first'):
            return
        xml = common.export_netlist(self.p.sch, self.out / 'netlist.xml', cwd=self.p.root)
        n = common.parse_netlist(xml)
        problems, notes = [], []
        # intent assertions
        intent_file = self.p.path(self.p.section('design').get('intent'))
        if intent_file:
            import intent
            problems += intent.check(n, tomllib.loads(intent_file.read_text(encoding='utf-8')))
            notes.append(f'intent {intent_file.name}')
        # symbol pins vs footprint pads, typed pins
        table = common.lib_table('fp', self.p.kicad_dir)
        extra_ok = set(self.g.get('extra_pads_allowed', []))
        checked = 0
        for ref, c in sorted(n['components'].items()):
            if c['exclude_from_board']:
                continue
            if not c['footprint']:
                problems.append(f'{ref}: no footprint'); continue
            path = common.footprint_file(c['footprint'], self.p.kicad_dir, table)
            if not path or not path.exists():
                problems.append(f'{ref}: footprint {c["footprint"]} not found in the library tables'); continue
            pads = common.footprint_pads(path)
            pins = n['pins'].get(ref, {})
            missing = sorted(set(pins) - set(pads))
            extra = sorted(set(pads) - set(pins) - {p.split('.', 1)[1] for p in extra_ok if p.startswith(ref + '.')})
            if missing:
                problems.append(f'{ref}: symbol pins without a pad in {c["footprint"]}: {missing}')
            if extra:
                problems.append(f'{ref}: pads without a symbol pin (list as "{ref}.<pad>" in [gate].extra_pads_allowed if intended): {extra}')
            untyped = sorted(num for num, (_, t) in pins.items() if t in (None, 'unspecified'))
            if untyped:
                problems.append(f'{ref}: pins with unspecified electrical type {untyped}')
            checked += 1
        notes.append(f'{checked} footprints vs symbols')
        # BOM fields
        bom = self.p.section('bom')
        fields = bom.get('required_fields', [])
        exempt = {e['ref'] for e in bom.get('exempt', [])}      # [{ref, why}]: e.g. a hand-soldered speaker
        if fields:
            for ref, c in sorted(n['components'].items()):
                if c['dnp'] or c['exclude_from_bom'] or ref in exempt:
                    continue
                empty = [f for f in fields if not c['fields'].get(f, '').strip()]
                if empty:
                    problems.append(f'{ref}: empty BOM fields {empty}')
            notes.append(f'BOM fields {fields}')
        register = self.p.path(bom.get('parts'))
        if register and register.exists():
            import csv
            rows = list(csv.DictReader(register.open(encoding='utf-8-sig')))
            known = {r.get('MPN', '').strip() for r in rows} | {r.get('LCSC', '').strip() for r in rows}
            key = bom.get('register_key', 'MPN')
            for ref, c in sorted(n['components'].items()):
                v = c['fields'].get(key, '').strip()
                if v and not c['dnp'] and v not in known:
                    problems.append(f'{ref}: {key} {v} is not in {register.name} (every part goes through selection)')
            notes.append(f'register {register.name}')
        write_json(self.out / 'netlist-check.json', {'problems': problems, 'components': len(n['components']), 'nets': len(n['nets'])})
        self.report('netlist', not problems, '; '.join(problems[:8]) if problems else ', '.join(notes))

    # ------------------------------------------------------------ metrics, simulation
    def metrics(self):
        if not self.g.get('metrics') or not self.p.pcb or not self.p.pcb.exists():
            return self.report('metrics', True, 'no [gate].metrics', skipped=True)
        import metrics
        values, failures, rules = metrics.evaluate(self.p)
        write_json(self.out / 'metrics.json', {'values': values, 'failures': failures})
        self.report('metrics', not failures, '; '.join(failures[:8]) if failures else f'{len(rules)} metrics within thresholds')

    def sim(self):
        if not self.g.get('sim'):
            return self.report('sim', True, 'no [gate].sim', skipped=True)
        import sim
        res = sim.run_all(self.p.path(self.g['sim']))
        write_json(self.out / 'sim.json', res)
        bad = [f"{b['id']}/{c}: {m}" for b in res['benches'] for c, m in b['failures']]
        self.report('sim', not bad, '; '.join(bad[:6]) if bad else f"{len(res['benches'])} benches, all assertions pass")

    # ------------------------------------------------------------ reproduction
    def design_files(self, root):
        """Files under root that belong to the design: what git would commit (tracked, or untracked and not
        ignored); without git, everything except scratch patterns."""
        files = [q for q in Path(root).rglob('*') if q.is_file() and not common.ignore_scratch(None, q.relative_to(root).parts)]
        rels = [q.relative_to(root).as_posix() for q in files]
        r = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=self.p.root, input='\n'.join(rels),
                           capture_output=True, text=True)
        if r.returncode in (0, 1):     # 1: nothing ignored; 128: not a git repository
            ignored = set(r.stdout.split('\n'))
            return {x for x in rels if x not in ignored}
        # no git: apply the project's own .gitignore patterns (simple fnmatch on each path part and the path)
        pats = []
        gi = self.p.root / '.gitignore'
        if gi.exists():
            pats = [l.strip().rstrip('/') for l in gi.read_text().splitlines() if l.strip() and not l.startswith('#')]
        def ignored_path(rel):
            parts = rel.split('/')
            return any(fnmatch.fnmatch(part, pat) for pat in pats for part in parts) or any(fnmatch.fnmatch(rel, pat) for pat in pats)
        return {x for x in rels if not ignored_path(x)}

    def reproduce(self):
        cmds = self.p.section('design').get('generate', [])
        if not cmds:
            return self.report('reproduce', True, 'no [design].generate', skipped=True)
        ignore = self.p.section('design').get('reproduce_ignore', [])
        with tempfile.TemporaryDirectory() as d:
            copy = common.copy_project(self.p.root, Path(d) / 'repo')
            env = dict(os.environ, PATH=os.pathsep.join([str(Path.home() / '.local/bin'), os.environ.get('PATH', '')]))
            for cmd in cmds:
                r = subprocess.run(cmd, shell=True, cwd=copy, capture_output=True, text=True, env=env)
                if r.returncode:
                    return self.report('reproduce', False, f'`{cmd}` failed: ' + (r.stdout + r.stderr).strip()[-300:])
            before = self.design_files(self.p.root)
            after = self.design_files(copy)
            changed = []
            for rel in sorted(before | after):
                if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
                    continue
                a, b = self.p.root / rel, copy / rel
                if not (a.exists() and b.exists()) or a.read_bytes() != b.read_bytes():
                    changed.append(rel + ('' if b.exists() else ' (removed)') + ('' if a.exists() else ' (new)'))
        self.report('reproduce', not changed, f'{len(changed)} files differ: ' + ', '.join(changed[:10]) if changed
                    else f'{len(cmds)} generator commands reproduce the design files')


ORDER = ['erc', 'drc', 'rules', 'zones', 'netlist', 'metrics', 'sim', 'reproduce']


def main():
    ap = argparse.ArgumentParser(description='pcbkit merge gate')
    ap.add_argument('--config'); ap.add_argument('--out', default='reports')
    ap.add_argument('--only', default=''); ap.add_argument('--skip', default='')
    a = ap.parse_args()
    p = Project(a.config)
    out = (p.root / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    only = [c for c in a.only.split(',') if c]
    skip = set(c for c in a.skip.split(',') if c) | set(p.section('gate').get('skip', []))
    g = Gate(p, out)
    print(f'pcbkit {common.KIT_VERSION} gate for {p.name} ({common.kicad_version()})', flush=True)
    for name in ORDER:
        if (only and name not in only) or name in skip:
            continue
        try:
            getattr(g, name)()
        except Exception as e:  # a crashed check is a failed check
            g.report(name, False, f'{type(e).__name__}: {e}')
    summary = {'project': p.name, 'kit': common.KIT_VERSION, 'kicad': common.kicad_version(), 'results': g.results,
               'skipped_by_config': sorted(skip)}
    write_json(out / 'summary.json', summary)
    failed = [r['check'] for r in g.results if not r['ok']]
    print('\n' + ('ALL CHECKS PASSED' if not failed else f'{len(failed)} CHECK(S) FAILED: ' + ', '.join(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
