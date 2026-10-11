"""Build the fabrication and review package for the current revision, only from a design that passes
the gate. Output: release/<name>-<revision>/ (not committed; attach it to the git tag's release).

  fab/gerbers/*        Gerber X2 for every used layer, Excellon drill (PTH and NPTH) and drill map
  fab/gerbers.zip      the same, zipped for the board house
  fab/ipc-d-356.d356   bare-board test netlist
  fab/panel/           only with [outputs].panel = "self": KiKit panel (layout/panel.toml), its DRC report,
                       render, Gerbers and JLC placement; refuses to build when the panel is not usable
  assembly/positions.csv, assembly/bom.csv            KiCad position file (fitted parts) and grouped BOM
  assembly/jlc-bom.csv, assembly/jlc-cpl.csv          JLCPCB format (Comment/Designator/Footprint/LCSC Part #)
  assembly/ibom.html                                  interactive BOM ([outputs].ibom)
  review/schematic.pdf, review/pcb.pdf               schematic and per-layer board plots
  review/kicanvas/                                   schematic and board in the browser ([outputs].kicanvas)
  board-stats.json, gate-summary.json, manifest.json, SHA256SUMS, README.txt

Refuses to run when the gate fails (pass --no-gate to build a package marked REVIEW ONLY) or when the
git tree has uncommitted design changes (--allow-dirty, also marked REVIEW ONLY). Optional outputs whose
tool is not installed are skipped and listed in README.txt; they do not change the status.

usage: python3 pcbkit/release.py [--config pcb.toml] [--no-gate] [--allow-dirty] [--step]
"""
import argparse, csv, datetime, hashlib, json, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import extras  # noqa: E402
from common import kicad_cli  # noqa: E402

PANEL_TEXT = {
    'self': 'panel: self-panelized with KiKit (fab/panel/); order the panel, assemble it with fab/panel/jlc-cpl.csv '
            'and assembly/jlc-bom.csv (every designator appears once per board in the CPL)',
    'fab': 'panel: none in this package; order single boards or let the board house panelize them',
    'ask': 'PANEL NOT DECIDED: set [outputs].panel in pcb.toml to "self" (KiKit, layout/panel.toml) or "fab" '
           '(board house) and record the decision in docs/DECISIONS.md',
}


def git(root, *args):
    r = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser(description='Fabrication and review package')
    ap.add_argument('--config'); ap.add_argument('--no-gate', action='store_true'); ap.add_argument('--allow-dirty', action='store_true')
    ap.add_argument('--step', action='store_true', help='also export STEP (needs the 3D model library)')
    a = ap.parse_args()
    p = common.Project(a.config)
    proj = p.section('project')
    opts = extras.outputs(p)
    rev = str(proj.get('revision', '0'))
    out = p.root / 'release' / f'{p.name}-{rev}'
    status = []

    commit = git(p.root, 'rev-parse', 'HEAD')
    if not commit:
        status.append('not built from a git commit (no traceable revision)')
    dirty = git(p.root, 'status', '--porcelain', '--untracked-files=no', '--', '.')
    if dirty:
        if not a.allow_dirty:
            sys.exit('uncommitted changes: commit them first (or --allow-dirty for a REVIEW ONLY package)\n' + dirty)
        status.append('built from a dirty working tree')

    gate_summary = None
    if a.no_gate:
        status.append('gate not run')
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).with_name('gate.py')), '--config', str(p.cfg_path), '--out', 'reports'],
                           cwd=p.root, text=True)
        gate_summary = json.loads((p.root / 'reports/summary.json').read_text())
        if r.returncode:
            sys.exit('the gate failed: no release package (fix the design, or --no-gate for a REVIEW ONLY package)')

    def fail(msg):
        shutil.rmtree(out, ignore_errors=True)   # never leave a half-built package that looks like a release
        sys.exit(msg)

    if out.exists():
        shutil.rmtree(out)
    fab, asm, rv = out / 'fab', out / 'assembly', out / 'review'
    for d in (fab, asm, rv):
        d.mkdir(parents=True, exist_ok=True)
    pcb, sch = p.pcb, p.sch
    cu = common.export_fab(pcb, fab, cwd=p.root)
    kicad_cli('pcb', 'export', 'ipcd356', '-o', fab / 'ipc-d-356.d356', pcb, cwd=p.root)
    positions = common.export_positions(pcb, asm / 'positions.csv', cwd=p.root)
    kicad_cli('pcb', 'export', 'stats', '--format', 'json', '-o', out / 'board-stats.json', pcb, cwd=p.root)
    if sch:
        fields = ['Reference', 'Value', 'Footprint', '${QUANTITY}', '${DNP}'] + p.section('bom').get('required_fields', [])
        kicad_cli('sch', 'export', 'bom', '--fields', ','.join(fields), '--labels', ','.join(f.strip('${}') for f in fields),
                  '--group-by', ','.join(['Value', 'Footprint'] + p.section('bom').get('required_fields', [])),
                  '--ref-range-delimiter', '', '-o', asm / 'bom.csv', sch, cwd=p.root)
        kicad_cli('sch', 'export', 'pdf', '-o', rv / 'schematic.pdf', sch, cwd=p.root)
    kicad_cli('pcb', 'export', 'pdf', '--mode-multipage', '--layers', ','.join(cu + ['F.Silkscreen', 'B.Silkscreen', 'F.Fab', 'B.Fab']),
              '--common-layers', 'Edge.Cuts', '--include-border-title', '-o', rv / 'pcb.pdf', pcb, cwd=p.root)
    if a.step:
        kicad_cli('pcb', 'export', 'step', '--subst-models', '-o', out / f'{p.name}.step', pcb, cwd=p.root)

    # BOM <-> positions, JLC files
    placed = {r['Ref'] for r in positions}
    bom_rows = list(csv.DictReader((asm / 'bom.csv').open(encoding='utf-8'))) if sch else []
    fitted = {}
    for r in bom_rows:
        if r.get('DNP', '').strip():
            continue
        for ref in r['Reference'].split(','):
            fitted[ref.strip()] = r
    smt = {ref for ref in fitted if ref in placed}
    problems = []
    if sch and set(fitted) - placed:
        status.append('fitted parts without placement (not machine-assembled): ' + ', '.join(sorted(set(fitted) - placed)))
    if sch and placed - set(fitted):
        problems.append('placed parts missing from the BOM: ' + ', '.join(sorted(placed - set(fitted))))
    lcsc_field = 'LCSC' if 'LCSC' in p.section('bom').get('required_fields', []) else None
    if lcsc_field:
        with (asm / 'jlc-bom.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
            for r in bom_rows:
                refs = [x.strip() for x in r['Reference'].split(',') if x.strip() in smt]
                if refs:
                    w.writerow([r['Value'], ','.join(refs), r['Footprint'].split(':')[-1], r.get(lcsc_field, '')])
        common.write_jlc_cpl(positions, smt, asm / 'jlc-cpl.csv')
    if problems:
        fail('package inconsistent: ' + '; '.join(problems))

    # panel: decided by the user ([outputs].panel), never guessed
    panel = None
    if opts['panel'] == 'self':
        try:
            panel = extras.panel(p, fab / 'panel', smt=smt)
        except extras.Unavailable as e:
            fail(f'[outputs].panel = "self" but {e}')
        if not panel['ok']:
            fail('panel not usable, no release package: ' + '; '.join(panel['problems']) + ' (try python3 pcbkit/extras.py panel)')
    elif opts['panel'] == 'ask':
        print('\n*** ' + PANEL_TEXT['ask'] + ' ***\n', file=sys.stderr)

    # optional outputs: skipped with a note when the tool is missing, never a reason to refuse
    optional = {}
    if opts['ibom']:
        optional['ibom'] = extras.attempt('ibom', extras.ibom, p, asm / 'ibom.html')[1] or 'assembly/ibom.html'
    if opts['kicanvas']:
        optional['kicanvas'] = extras.attempt('kicanvas', extras.kicanvas, p, rv / 'kicanvas')[1] or 'review/kicanvas/'

    released = not status
    notes = [v for v in optional.values() if 'skipped' in v or 'failed' in v]
    (out / 'README.txt').write_text(
        f"{p.name} revision {rev}: {'RELEASE CANDIDATE' if released else 'REVIEW ONLY - NOT FOR FABRICATION'}\n"
        + ''.join(f'- {s}\n' for s in status)
        + f'git commit: {commit or "none"}\n'
        + PANEL_TEXT[opts['panel']] + '\n'
        + (f"  panel: {panel['boards']} boards, {panel['size_mm'][0]} x {panel['size_mm'][1]} mm, one piece, panel DRC clean\n" if panel else '')
        + ''.join(f'optional output {n}\n' for n in notes)
        + ('review/kicanvas/: open over HTTP, see review/kicanvas/README.txt\n' if (rv / 'kicanvas').exists() else '')
        + 'Check every part in the board house placement preview (pin 1, diode polarity, connector orientation)\n'
        'before ordering: KiCad rotations and JLC rotations differ for some packages.\n', encoding='utf-8')
    if gate_summary:
        common.write_json(out / 'gate-summary.json', gate_summary)
    files = sorted(f for f in out.rglob('*') if f.is_file())
    sums = {f.relative_to(out).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    common.write_json(out / 'manifest.json', {
        'project': p.name, 'revision': rev, 'status': 'release-candidate' if released else 'review-only', 'notes': status,
        'git_commit': commit, 'kicad': common.kicad_version(), 'pcbkit': common.KIT_VERSION,
        'built': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'copper_layers': cu, 'fitted_parts': len(fitted), 'machine_placed': len(smt),
        'panel': {'mode': opts['panel'], **({k: panel[k] for k in ('config', 'boards', 'size_mm', 'drc', 'placements')} if panel else {})},
        'optional_outputs': optional, 'files': sums})
    (out / 'SHA256SUMS').write_text(''.join(f'{h}  {n}\n' for n, h in sums.items()))
    print(f"{'RELEASE CANDIDATE' if released else 'REVIEW ONLY'}: {p.rel(out)} ({len(files)} files)")
    for s in status + [PANEL_TEXT[opts['panel']]] + notes:
        print('  - ' + s)


if __name__ == '__main__':
    main()
