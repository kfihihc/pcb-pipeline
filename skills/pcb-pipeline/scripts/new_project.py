"""Create a board project from the pcb-pipeline template, adopt an existing KiCad project, or update the
vendored tools (pcbkit/) of a project to this version.

  new_project.py <dir> --name usb-ldo --title "USB-C 3.3 V LDO" [--layers 2] [--size 30x20]
                 [--mode code|schematic] [--license CERN-OHL-S-2.0]
  new_project.py <dir> --adopt --pcb board.kicad_pcb --sch board.kicad_sch --name x
                 adds pcb.toml, docs/, checks/, sim/, design/intent.toml, parts/ and pcbkit/ to an existing
                 KiCad project without touching its design files (existing files are never overwritten)
  new_project.py <dir> --update-kit
                 replaces <dir>/pcbkit/ with this kit (a reviewed change: commit it on its own branch)

The project gets its own copy of the tools (pcbkit/, standard library + KiCad's pcbnew only), so CI and
colleagues run exactly the version the project was checked with.
"""
import argparse, datetime, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent / 'kit'
TEMPLATE = HERE.parent / 'assets' / 'template'


def kicad_version():
    try:
        v = subprocess.run(['kicad-cli', 'version'], capture_output=True, text=True).stdout.strip()
        return re.match(r'[\d.]+', v).group(0)
    except Exception:
        return '10.0.6'


def vendor_kit(dest):
    target = dest / 'pcbkit'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(KIT, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    sums = {f.relative_to(target).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(target.rglob('*')) if f.is_file()}
    (target / 'MANIFEST.json').write_text(json.dumps({'version': (KIT / 'VERSION').read_text().strip(), 'files': sums}, indent=1) + '\n')
    return (KIT / 'VERSION').read_text().strip()


def render(text, values):
    return re.sub(r'\{\{(\w+)\}\}', lambda m: str(values.get(m.group(1), m.group(0))), text)


def copy_template(dest, values, overwrite, adopt=False):
    written, kept = [], []
    has_readme = any(dest.glob('README*'))
    has_ci = any((dest / d).glob('*.y*ml') for d in ('.gitea/workflows', '.github/workflows', '.forgejo/workflows') if (dest / d).is_dir())
    for src in sorted(TEMPLATE.rglob('*')):
        if src.is_dir():
            continue
        rel = src.relative_to(TEMPLATE)
        r = rel.as_posix()
        if values['mode'] != 'code' and r == 'design/board.py':
            continue
        if adopt and ((r == 'README.md' and has_readme) or (r.startswith('.gitea/') and has_ci) or r.startswith('layout/')):
            kept.append(r + ' (skipped: existing project)'); continue
        out = dest / rel
        if out.exists() and not overwrite:
            kept.append(rel.as_posix()); continue
        out.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        try:
            out.write_text(render(data.decode('utf-8'), values), encoding='utf-8')
        except UnicodeDecodeError:
            out.write_bytes(data)
        written.append(rel.as_posix())
    return written, kept


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('dir')
    ap.add_argument('--name'); ap.add_argument('--title'); ap.add_argument('--layers', type=int, default=2)
    ap.add_argument('--size', default='30x20', help='outline WxH in mm'); ap.add_argument('--mode', default='code', choices=['code', 'schematic'])
    ap.add_argument('--license', default='CERN-OHL-S-2.0')
    ap.add_argument('--adopt', action='store_true'); ap.add_argument('--pcb'); ap.add_argument('--sch')
    ap.add_argument('--update-kit', action='store_true')
    a = ap.parse_args()
    dest = Path(a.dir).resolve()

    if a.update_kit:
        if not (dest / 'pcb.toml').exists():
            sys.exit(f'{dest} has no pcb.toml')
        old = json.loads((dest / 'pcbkit/MANIFEST.json').read_text())['version'] if (dest / 'pcbkit/MANIFEST.json').exists() else '?'
        new = vendor_kit(dest)
        print(f'pcbkit {old} -> {new} in {dest}/pcbkit; run the gate and commit the update on its own branch')
        return

    name = a.name or dest.name
    w, h = (float(x) for x in a.size.lower().split('x'))
    values = {'name': name, 'title': a.title or name, 'layers': a.layers, 'width': f'{w:g}', 'height': f'{h:g}',
              'mode': 'schematic' if a.adopt else a.mode, 'license': a.license, 'kicad': kicad_version(),
              'date': datetime.date.today().isoformat(), 'kit_version': (KIT / 'VERSION').read_text().strip(),
              'generate': '"uv run python design/board.py"' if (a.mode == 'code' and not a.adopt) else ''}
    if a.adopt:
        if not (dest / (a.pcb or '')).exists() and not (dest / (a.sch or '')).exists():
            sys.exit('--adopt needs --pcb and/or --sch relative to the project directory')
    elif dest.exists() and any(dest.iterdir()):
        sys.exit(f'{dest} is not empty: use --adopt for an existing KiCad project')
    dest.mkdir(parents=True, exist_ok=True)
    written, kept = copy_template(dest, values, overwrite=False, adopt=a.adopt)
    if a.adopt:
        cfg = (dest / 'pcb.toml').read_text(encoding='utf-8')
        if 'pcb.toml' in written:   # point the fresh manifest at the existing files
            cfg = cfg.replace(f'pcb = "hw/{name}.kicad_pcb"', f'pcb = "{a.pcb}"' if a.pcb else '# pcb = ""')
            cfg = cfg.replace(f'sch = "hw/{name}.kicad_sch"', f'sch = "{a.sch}"' if a.sch else '# sch = ""')
            (dest / 'pcb.toml').write_text(cfg, encoding='utf-8')
    version = vendor_kit(dest)
    print(f'{"adopted" if a.adopt else "created"} {dest} (pcbkit {version}, KiCad {values["kicad"]})')
    print('  written: ' + ', '.join(written))
    if kept:
        print('  kept existing: ' + ', '.join(kept))
    print('next: git init (if needed), fill docs/SPEC.md, then select parts (pcb-parts skill)')


if __name__ == '__main__':
    main()
