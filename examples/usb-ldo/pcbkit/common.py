"""Shared helpers for the pcbkit tools: the project manifest (pcb.toml), kicad-cli, netlists and
footprint library tables. Standard library only, so CI can run it with the plain python3 of the
kicad/kicad image (Python 3.11+ for tomllib).
"""
import fnmatch, json, os, re, shutil, subprocess, sys, tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

KIT = Path(__file__).resolve().parent
KIT_VERSION = (KIT / 'VERSION').read_text().strip() if (KIT / 'VERSION').exists() else 'unknown'

# Generated or local files that never belong to the design (used by copies and reproduction checks).
SCRATCH = ['.git', '.venv', '__pycache__', 'reports', 'exports', 'work', 'release', '*.kicad_prl', '*.lck',
           '*-backups', 'fp-info-cache', '~*', '*.pyc', '_autosave-*']


class Project:
    """A board project: the directory that holds pcb.toml."""

    def __init__(self, config=None):
        if config:
            self.cfg_path = Path(config).resolve()
        else:
            here = Path.cwd().resolve()
            found = next((d / 'pcb.toml' for d in [here, *here.parents] if (d / 'pcb.toml').exists()), None)
            if not found:
                sys.exit('pcb.toml not found: run inside a board project or pass --config')
            self.cfg_path = found
        self.root = self.cfg_path.parent
        self.cfg = tomllib.loads(self.cfg_path.read_text(encoding='utf-8'))
        p = self.cfg.get('project', {})
        self.name = p.get('name', self.root.name)
        self.pcb = self.path(p.get('pcb'))
        self.sch = self.path(p.get('sch'))
        self.pro = self.pcb.with_suffix('.kicad_pro') if self.pcb else (self.sch.with_suffix('.kicad_pro') if self.sch else None)
        self.dru = self.pcb.with_suffix('.kicad_dru') if self.pcb else None
        self.kicad_dir = (self.pcb or self.sch).parent if (self.pcb or self.sch) else self.root   # lib tables, ${KIPRJMOD}

    def path(self, rel):
        return (self.root / rel) if rel else None

    def section(self, name):
        return self.cfg.get(name, {})

    def rel(self, path):
        return Path(path).resolve().relative_to(self.root).as_posix()


def kicad_cli(*args, cwd=None, check=True):
    r = subprocess.run(['kicad-cli', *map(str, args)], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError('kicad-cli %s failed: %s' % (' '.join(map(str, args[:3])), (r.stdout + r.stderr).strip()[-600:]))
    return r


def kicad_version():
    r = subprocess.run(['kicad-cli', 'version'], capture_output=True, text=True)
    return r.stdout.strip()


def ignore_scratch(directory, names):
    return {n for n in names if any(fnmatch.fnmatch(n, pat) for pat in SCRATCH)}


def copy_project(root, dest):
    """Copy a project without scratch files (for reproduction checks and rule experiments)."""
    shutil.copytree(root, dest, symlinks=True, ignore=ignore_scratch)
    return Path(dest)


# ---------------------------------------------------------------- netlists

def export_netlist(sch, out, cwd=None):
    kicad_cli('sch', 'export', 'netlist', '--format', 'kicadxml', '-o', out, sch, cwd=cwd)
    return Path(out)


def parse_netlist(path):
    """KiCad XML netlist -> {'components': {ref: {...}}, 'nets': {name: [(ref, pin), ...]},
    'pins': {ref: {num: (name, type)}}}. Power and flag symbols (#PWR, #FLG) are left out."""
    x = ET.parse(path).getroot()
    libparts = {}
    for lp in x.find('libparts') if x.find('libparts') is not None else []:
        pins = {p.get('num'): (p.get('name'), p.get('type')) for p in lp.iter('pin')}
        libparts[(lp.get('lib'), lp.get('part'))] = pins
    comps, pins = {}, {}
    for c in x.find('components'):
        ref = c.get('ref')
        if ref.startswith('#'):
            continue
        props = {p.get('name'): p.get('value', '') for p in c.findall('property')}
        fields = {f.get('name'): (f.text or '') for f in c.iter('field')}
        src = c.find('libsource')
        lib, part = (src.get('lib'), src.get('part')) if src is not None else (None, None)
        sp = c.find('sheetpath')
        stamp = (c.findtext('tstamps') or '').split()
        comps[ref] = {'value': (c.findtext('value') or ''), 'footprint': (c.findtext('footprint') or ''),
                      'lib_id': f'{lib}:{part}', 'fields': fields, 'dnp': 'dnp' in props,
                      'exclude_from_bom': 'exclude_from_bom' in props, 'exclude_from_board': 'exclude_from_board' in props,
                      'sheet': sp.get('names') if sp is not None else '/',
                      'path': ((sp.get('tstamps') if sp is not None else '/') + stamp[0]) if stamp else '',
                      'sheetname': props.get('Sheetname', ''), 'sheetfile': props.get('Sheetfile', '')}
        lpins = libparts.get((lib, part), {})
        unit_pins = [p.get('num') for p in c.iter('pin')]
        pins[ref] = {n: lpins.get(n, (None, None)) for n in (unit_pins or lpins)}
    nets = {}
    for n in x.find('nets'):
        members = [(m.get('ref'), m.get('pin')) for m in n.findall('node') if not m.get('ref', '').startswith('#')]
        if members:
            nets[n.get('name')] = members
    return {'components': comps, 'nets': nets, 'pins': pins}


def pin_to_net(netlist):
    return {m: name for name, members in netlist['nets'].items() for m in members}


# KiCad stores some characters of net names escaped on the board ("{slash}" for "/" in a pin name);
# netlist exports print them unescaped.
_ESC = {'slash': '/', 'backslash': '\\', 'colon': ':', 'lt': '<', 'gt': '>', 'dblquote': '"', 'quote': "'",
        'return': '\n', 'tab': '\t', 'space': ' ', 'comma': ','}


def unescape(name):
    return re.sub(r'\{(\w+)\}', lambda m: _ESC.get(m.group(1), m.group(0)), name or '')


def board_net_name(name):
    """Net name as KiCad writes it on the board for a netlist (unescaped) name."""
    if name.startswith('unconnected-(') and name.endswith(')'):
        return 'unconnected-(' + name[len('unconnected-('):-1].replace('/', '{slash}') + ')'
    return name


# ---------------------------------------------------------------- footprint libraries

def _expand(uri, project_dir):
    env = {'KIPRJMOD': str(project_dir)}
    for v in ('10', '9', '8'):
        env.setdefault(f'KICAD{v}_FOOTPRINT_DIR', os.environ.get(f'KICAD{v}_FOOTPRINT_DIR', '/usr/share/kicad/footprints'))
        env.setdefault(f'KICAD{v}_SYMBOL_DIR', os.environ.get(f'KICAD{v}_SYMBOL_DIR', '/usr/share/kicad/symbols'))
        env.setdefault(f'KICAD{v}_3DMODEL_DIR', os.environ.get(f'KICAD{v}_3DMODEL_DIR', '/usr/share/kicad/3dmodels'))
    return re.sub(r'\$\{(\w+)\}', lambda m: env.get(m.group(1), os.environ.get(m.group(1), m.group(0))), uri)


def lib_table(kind, project_dir):
    """{nickname: path} from the project's fp-lib-table / sym-lib-table, then the user's or KiCad's default table."""
    name = 'fp-lib-table' if kind == 'fp' else 'sym-lib-table'
    tables = [Path(project_dir) / name]
    for v in ('10.0', '9.0'):
        user = Path.home() / '.config/kicad' / v / name
        if user.exists():
            tables.append(user); break
    else:
        tables.append(Path('/usr/share/kicad/template') / name)
    out = {}
    for t in tables:
        if not t.exists():
            continue
        for m in re.finditer(r'\(lib\s+\(name\s+"?([^")\s]+)"?\)(.*?)\(uri\s+"?([^")\s]+)"?\)', t.read_text(encoding='utf-8')):
            out.setdefault(m.group(1), Path(_expand(m.group(3), project_dir)))
    return out


def ensure_lib_tables(kicad_dir, sym_libs=(), fp_libs=()):
    """Add the system libraries a design uses to the project's own sym-lib-table / fp-lib-table, so ERC,
    DRC and colleagues resolve them without relying on anyone's global KiCad configuration."""
    changed = []
    for kind, libs, var, ext, top in (('sym', sym_libs, 'KICAD10_SYMBOL_DIR', '.kicad_sym', 'sym_lib_table'),
                                      ('fp', fp_libs, 'KICAD10_FOOTPRINT_DIR', '.pretty', 'fp_lib_table')):
        path = Path(kicad_dir) / f'{kind}-lib-table'
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        have = set(re.findall(r'\(lib\s+\(name\s+"?([^")\s]+)"?\)', text))
        system = Path(_expand('${%s}' % var, kicad_dir))
        add = sorted(l for l in set(libs) - have if (system / f'{l}{ext}').exists())
        if not add:
            continue
        entries = [m.group(0) for m in re.finditer(r'\(lib\s+\(name.*?\)\)\s*\n', text)] if text else []
        entries += [f'  (lib (name "{l}")(type "KiCad")(uri "${{{var}}}/{l}{ext}")(options "")(descr ""))\n' for l in add]
        entries.sort(key=lambda e: re.search(r'\(name\s+"?([^")\s]+)', e).group(1))
        path.write_text(f'({top}\n  (version 7)\n' + ''.join('  ' + e.strip() + '\n' for e in entries) + ')\n', encoding='utf-8')
        changed.append(f'{path.name}: +{", ".join(add)}')
    return changed


def footprint_file(fpid, project_dir, table=None):
    lib, _, name = fpid.partition(':')
    table = table if table is not None else lib_table('fp', project_dir)
    if lib not in table:
        return None
    return table[lib] / f'{name}.kicad_mod'


def footprint_pads(path):
    """{pad number: pad type} of a .kicad_mod; unnumbered and non-plated mechanical holes are left out."""
    text = Path(path).read_text(encoding='utf-8')
    pads = {}
    for quoted, bare, kind in re.findall(r'\(pad\s+(?:"([^"]*)"|([^\s()"]+))\s+(\w+)', text):
        num = quoted or bare          # older and converted footprints write pad numbers unquoted
        if num and kind != 'np_thru_hole':
            pads.setdefault(num, kind)
    return pads


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')


# ---------------------------------------------------------------- fabrication exports (release.py, extras.py panel)

FAB_LAYERS = ['F.Mask', 'B.Mask', 'F.Paste', 'B.Paste', 'F.Silkscreen', 'B.Silkscreen', 'Edge.Cuts']


def copper_layers(pcb):
    import kicad_compat as kc
    b = kc.load_board(pcb)
    return [kc.pcbnew.LayerName(l) for l in b.GetEnabledLayers().CuStack()]


def export_fab(pcb, dest, cwd=None):
    """Gerber X2 for every used layer plus Excellon drill (PTH and NPTH) and drill map into dest/gerbers/,
    zipped as dest/gerbers.zip. Returns the copper layer names."""
    import zipfile
    gb = Path(dest) / 'gerbers'
    gb.mkdir(parents=True, exist_ok=True)
    cu = copper_layers(pcb)
    kicad_cli('pcb', 'export', 'gerbers', '--layers', ','.join(cu + FAB_LAYERS), '--subtract-soldermask', '-o', str(gb) + '/', pcb, cwd=cwd)
    kicad_cli('pcb', 'export', 'drill', '--format', 'excellon', '--excellon-separate-th', '--generate-map', '--map-format', 'pdf',
              '-o', str(gb) + '/', pcb, cwd=cwd)
    with zipfile.ZipFile(Path(dest) / 'gerbers.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(gb.iterdir()):
            z.write(f, f.name)
    return cu


def export_positions(pcb, out, cwd=None):
    """kicad-cli position file (csv, mm, fitted parts only) -> list of rows (Ref, Val, Package, PosX, PosY, Rot, Side)."""
    import csv
    kicad_cli('pcb', 'export', 'pos', '--format', 'csv', '--units', 'mm', '--exclude-dnp', '-o', out, pcb, cwd=cwd)
    return list(csv.DictReader(Path(out).open(encoding='utf-8')))


def write_jlc_cpl(rows, refs, out):
    """JLCPCB placement file (Designator, Mid X, Mid Y, Layer, Rotation) for the position rows whose Ref is in refs.
    A panel has one row per board for each designator."""
    import csv
    with Path(out).open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
        for r in rows:
            if r['Ref'] in refs:
                w.writerow([r['Ref'], f"{float(r['PosX']):.4f}mm", f"{float(r['PosY']):.4f}mm",
                            'Top' if r['Side'] == 'top' else 'Bottom', f"{float(r['Rot']):g}"])
