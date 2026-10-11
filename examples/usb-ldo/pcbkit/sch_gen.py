"""Readable KiCad schematic from a netlist, for code-first designs (SKiDL, tscircuit, project generators).

Each symbol is placed unrotated in a grid; every pin gets a short wire and a net label, so connectivity
is by name and nothing is auto-routed. Parts are grouped into blocks: parts joined by signal nets
(not power nets) form a block, two-pin parts that only touch power nets (decoupling capacitors) join
the IC they share a supply with, and blocks with connectors come first. Symbol UUIDs come from the
netlist time stamps, so footprints stay linked to their symbols across regenerations.

The output is checked before it is written: KiCad's own netlist export of the new schematic must have
the same connectivity as the input netlist, pin for pin.

usage: python3 pcbkit/sch_gen.py design/board.net hw/board.kicad_sch [--title T] [--rev R] [--company C]
           [--power-flag VBUS --power-flag GND] [--power-nets "GND,+*,VBUS,VCC*"] [--drop-field "SKiDL Line"]
Input: KiCad S-expression netlist (SKiDL generate_netlist, Eeschema) or KiCad XML netlist.
Pins left open on purpose: list them in the part field NC_PINS ("4,5"); they get no-connect flags. Every
other open pin is left for ERC to report.
"""
import argparse, fnmatch, re, subprocess, sys, tempfile, uuid
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

NS = uuid.UUID('6f1c1f6a-3f4b-4f57-9a49-2f0d2a8f9c11')
STUB = 2.54
FONT = 1.27
PAPERS = [('A4', 297, 210), ('A3', 420, 297), ('A2', 594, 420), ('A1', 841, 594)]


def uid(*parts):
    return str(uuid.uuid5(NS, '/'.join(map(str, parts))))


def snap(v, g=2.54):
    return round(round(v / g) * g, 4)


def q(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'


# ------------------------------------------------------------------ S-expressions
TOKEN = re.compile(r'\(|\)|"(?:\\.|[^"\\])*"|[^\s()"]+')


def parse(text):
    stack, cur = [], []
    for m in TOKEN.finditer(text):
        t = m.group(0)
        if t == '(':
            stack.append(cur); cur = []
        elif t == ')':
            done = cur; cur = stack.pop(); cur.append(done)
        else:
            cur.append(t[1:-1].replace('\\"', '"').replace('\\\\', '\\') if t.startswith('"') else t)
    return cur


def find(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def first(node, key, default=None):
    r = find(node, key)
    return r[0] if r else default


def block_end(text, start):
    """Index after the parenthesis that closes the one at text[start]."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError('unbalanced')


# ------------------------------------------------------------------ netlists
def read_netlist(path, drop_fields):
    text = Path(path).read_text(encoding='utf-8')
    comps, nets = [], {}
    if text.lstrip().startswith('<'):
        x = ET.fromstring(text)
        for c in x.find('components'):
            src = c.find('libsource')
            fields = {f.get('name'): f.text or '' for f in c.iter('field')}
            comps.append({'ref': c.get('ref'), 'value': c.findtext('value') or '', 'footprint': c.findtext('footprint') or '',
                          'lib_id': f"{src.get('lib')}:{src.get('part')}", 'fields': fields,
                          'stamp': (c.findtext('tstamps') or '').split()[0] if c.findtext('tstamps') else ''})
        for n in x.find('nets'):
            nets[n.get('name')] = [(m.get('ref'), m.get('pin')) for m in n.findall('node')]
    else:
        root = parse(text)[0]
        for c in find(first(root, 'components'), 'comp'):
            def val(k, c=c):
                x = first(c, k)
                return x[1] if x and len(x) > 1 else ''
            fields = {}
            for f in find(first(c, 'fields') or [], 'field'):
                name = first(f, 'name')[1]
                fields[name] = f[2] if len(f) > 2 and isinstance(f[2], str) else ''
            src = first(c, 'libsource')
            comps.append({'ref': val('ref'), 'value': val('value'), 'footprint': val('footprint'),
                          'lib_id': f"{first(src, 'lib')[1]}:{first(src, 'part')[1]}", 'fields': fields,
                          'stamp': (first(c, 'tstamps') or ['', ''])[1].split()[0] if first(c, 'tstamps') else ''})
        for n in find(first(root, 'nets'), 'net'):
            nets[first(n, 'name')[1]] = [(first(m, 'ref')[1], first(m, 'pin')[1]) for m in find(n, 'node')]
    for c in comps:
        for f in drop_fields:
            c['fields'].pop(f, None)
    return comps, nets


def normalize_netlist(path):
    """Remove what changes on every run (export date, SKiDL source line numbers) so a committed netlist
    only changes when the circuit does."""
    text = Path(path).read_text(encoding='utf-8')
    new = re.sub(r'\(date\s+"[^"]*"\)', '(date "")', text)
    new = re.sub(r'\s*\(field\s+\(name\s+"SKiDL Line"\)\s*"[^"]*"\)', '', new)
    if new != text:
        Path(path).write_text(new, encoding='utf-8')


# ------------------------------------------------------------------ library symbols
class Library:
    def __init__(self, project_dir):
        self.table = common.lib_table('sym', project_dir)
        self.files = {}

    def raw(self, lib, name):
        """Raw text of a top-level symbol in a .kicad_sym file."""
        if lib not in self.table:
            raise SystemExit(f'symbol library {lib} is not in the library tables')
        if lib not in self.files:
            self.files[lib] = self.table[lib].read_text(encoding='utf-8')
        text = self.files[lib]
        m = re.search(r'\n\s*\(symbol\s+"%s"\s' % re.escape(name), text)
        if not m:
            raise SystemExit(f'{lib}:{name} not found in {self.table[lib]}')
        start = text.index('(', m.start())
        return text[start:block_end(text, start)]

    def flat(self, lib_id):
        """(embedded text named "Lib:Name", parsed tree) with `extends` resolved."""
        lib, _, name = lib_id.partition(':')
        raw = self.raw(lib, name)
        tree = parse(raw)[0]
        ext = first(tree, 'extends')
        if ext:
            base_raw = self.raw(lib, ext[1])
            # derived symbol: base graphics and pins, derived properties
            props = {p[1]: p for p in find(tree, 'property')}
            text = re.sub(r'\(symbol\s+"%s_(\d+_\d+)"' % re.escape(ext[1]), lambda m: f'(symbol "{name}_{m.group(1)}"', base_raw)
            for key, p in props.items():
                text = re.sub(r'(\(property\s+"%s"\s+)"(?:\\.|[^"\\])*"' % re.escape(key),
                              lambda m, v=p[2]: m.group(1) + q(v), text, count=1)
            raw = text
            tree = parse(raw)[0]
            base_name = ext[1]
        else:
            base_name = name
        embedded = re.sub(r'^\(symbol\s+"%s"' % re.escape(base_name), f'(symbol {q(lib_id)}', raw, count=1)
        return embedded, tree


def unit_geometry(tree, name):
    """{unit: {'pins': [(num, name, x, y, angle, length, type)], 'bbox': (x0, y0, x1, y1)}} in symbol coordinates."""
    units = {}
    for sub in find(tree, 'symbol'):
        m = re.match(r'.*_(\d+)_(\d+)$', sub[1])
        if not m:
            continue
        u, style = int(m.group(1)), int(m.group(2))
        if style not in (0, 1):
            continue
        g = units.setdefault(u, {'pins': [], 'pts': []})
        for p in find(sub, 'pin'):
            at = first(p, 'at'); ln = float((first(p, 'length') or [0, 0])[1])
            x, y, ang = float(at[1]), float(at[2]), int(float(at[3])) if len(at) > 3 else 0
            g['pins'].append((first(p, 'number')[1], first(p, 'name')[1], x, y, ang, ln, p[1]))
            g['pts'] += [(x, y)]
        for kind in ('rectangle',):
            for r in find(sub, kind):
                s, e = first(r, 'start'), first(r, 'end')
                g['pts'] += [(float(s[1]), float(s[2])), (float(e[1]), float(e[2]))]
        for pl in find(sub, 'polyline'):
            for xy in find(first(pl, 'pts') or [], 'xy'):
                g['pts'].append((float(xy[1]), float(xy[2])))
        for c in find(sub, 'circle'):
            ce, r = first(c, 'center'), float(first(c, 'radius')[1])
            g['pts'] += [(float(ce[1]) - r, float(ce[2]) - r), (float(ce[1]) + r, float(ce[2]) + r)]
        for a in find(sub, 'arc'):
            for key in ('start', 'mid', 'end'):
                v = first(a, key)
                if v:
                    g['pts'].append((float(v[1]), float(v[2])))
    common_unit = units.pop(0, {'pins': [], 'pts': []})
    if not units:
        units = {1: {'pins': [], 'pts': []}}
    out = {}
    for u, g in units.items():
        pts = g['pts'] + common_unit['pts'] or [(0, 0)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out[u] = {'pins': g['pins'] + common_unit['pins'], 'bbox': (min(xs), min(ys), max(xs), max(ys))}
    return out


OUTWARD = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}      # schematic coordinates (y down)
LABEL_ANGLE = {(-1, 0): 180, (1, 0): 0, (0, 1): 270, (0, -1): 90}


def text_len(s):
    return len(s) * FONT * 0.72 + 3.0      # global label flag around the text


# ------------------------------------------------------------------ grouping
def blocks(comps, nets, power_patterns, max_signal=6):
    def is_power(n):
        return any(fnmatch.fnmatchcase(n, p) for p in power_patterns) or len(nets[n]) > max_signal
    refs = [c['ref'] for c in comps]
    parent = {r: r for r in refs}

    def find_root(r):
        while parent[r] != r:
            parent[r] = parent[parent[r]]; r = parent[r]
        return r
    for n, members in nets.items():
        if is_power(n) or n.startswith('unconnected-'):
            continue
        rs = [m[0] for m in members if m[0] in parent]
        for r in rs[1:]:
            parent[find_root(r)] = find_root(rs[0])
    groups = {}
    for r in refs:
        groups.setdefault(find_root(r), []).append(r)
    by_ref = {c['ref']: c for c in comps}
    pins_of = {}
    for n, members in nets.items():
        for r, _ in members:
            pins_of.setdefault(r, set()).add(n)
    # passives on power nets only join the IC block that shares one of their nets
    for root, members in list(groups.items()):
        if len(members) == 1 and members[0][0] in 'CRLF' and not any(m.startswith('#') for m in members):
            r = members[0]
            target = next((g for g, ms in groups.items() if g != root and any(x[0] == 'U' for x in ms)
                           and any((pins_of.get(r, set()) & pins_of.get(x, set())) - {'GND'} for x in ms if x[0] == 'U')), None)
            if target:
                groups[target].append(r); del groups[root]

    def key(r):
        m = re.match(r'([#A-Za-z_]+)(\d*)', r)
        prefix_rank = {'J': 0, 'P': 0, 'U': 1, 'Q': 2, 'D': 3}.get(m.group(1).lstrip('#')[:1], 4)
        return (prefix_rank, m.group(1), int(m.group(2) or 0))
    out = [sorted(ms, key=key) for ms in groups.values()]
    out.sort(key=lambda ms: (min(key(r) for r in ms)[0] if not ms[0].startswith('#') else 9, key(ms[0])))
    return out


# ------------------------------------------------------------------ writer
def generate(net_path, out_path, title, rev, company, power_flags, power_patterns, drop_fields, project_dir):
    comps, nets = read_netlist(net_path, drop_fields)
    lib = Library(project_dir)
    for i, name in enumerate(power_flags, 1):
        if name not in nets:
            raise SystemExit(f'--power-flag {name}: no such net')
        ref = f'#FLG{i:02}'
        comps.append({'ref': ref, 'value': 'PWR_FLAG', 'footprint': '', 'lib_id': 'power:PWR_FLAG', 'fields': {}, 'stamp': uid('flag', name)})
        nets[name].append((ref, '1'))
    pin_net = {m: n for n, ms in nets.items() for m in ms}
    symbols, geo = {}, {}
    for c in comps:
        if c['lib_id'] not in symbols:
            text, tree = lib.flat(c['lib_id'])
            symbols[c['lib_id']] = text
            geo[c['lib_id']] = unit_geometry(tree, c['lib_id'].split(':')[1])
    root_uuid = uid('root', Path(out_path).stem)
    project = Path(out_path).stem
    items, placed = [], []
    # cells: (comp, unit, width, height, offsets)
    order = blocks(comps, nets, power_patterns)
    by_ref = {c['ref']: c for c in comps}
    margin = 12.7
    blocks_cells = []
    for grp in order:
        row = []
        for ref in grp:
            c = by_ref[ref]
            for u, g in sorted(geo[c['lib_id']].items()):
                x0, y0, x1, y1 = g['bbox']
                left = right = top = bottom = 0.0
                for num, pname, px, py, ang, ln, kind in g['pins']:
                    net = pin_net.get((ref, num))
                    ext = STUB + (text_len(net) if net else 0)
                    d = OUTWARD.get(ang % 360, (-1, 0))
                    if d == (-1, 0): left = max(left, ext)
                    if d == (1, 0): right = max(right, ext)
                    if d == (0, 1): bottom = max(bottom, ext)
                    if d == (0, -1): top = max(top, ext)
                dirs = {OUTWARD.get(pp[4] % 360, (-1, 0)) for pp in g['pins']}
                if (0, -1) not in dirs and (0, 1) not in dirs:
                    mode = 'tb'          # reference above, value below
                elif (0, -1) not in dirs:
                    mode = 'top'
                elif (0, 1) not in dirs:
                    mode = 'bottom'
                elif (1, 0) not in dirs:
                    mode = 'right'
                elif (-1, 0) not in dirs:
                    mode = 'left'
                else:
                    mode = 'top'
                field_w = max(text_len(ref), text_len(c['value'])) + 1.27
                pad_t = {'tb': 3.81, 'top': 6.35, 'bottom': 1.27, 'right': 1.27, 'left': 1.27}[mode]
                pad_b = {'tb': 3.81, 'top': 1.27, 'bottom': 6.35, 'right': 1.27, 'left': 1.27}[mode]
                if mode == 'right':
                    right = max(right, field_w)
                if mode == 'left':
                    left = max(left, field_w)
                w = (x1 - x0) + left + right + 5.08
                h = (y1 - y0) + top + bottom + pad_t + pad_b
                ox = left - x0 + 2.54
                oy = top + y1 + pad_t
                side_fields = (mode, top, bottom)
                row.append((c, u, w, h, ox, oy, side_fields))
        blocks_cells.append((sum(cl[2] for cl in row), max(cl[3] for cl in row), row))
    # pick the smallest paper on which the blocks flow without overlapping the title block
    for paper in PAPERS:
        usable_w, usable_h = paper[1] - 2 * margin - 5.08, paper[2] - 2 * margin - 38.0
        x = y = 0.0; row_h = 0.0; spots = []
        for bw, bh, row in blocks_cells:
            if x and x + bw > usable_w:
                x = 0.0; y += row_h + 5.08; row_h = 0.0
            spots.append((x, y)); x += bw + 7.62; row_h = max(row_h, bh)
        if y + row_h <= usable_h and max(bw for bw, _, _ in blocks_cells) <= usable_w:
            break
    layout = []
    for (bx, by), (bw, bh, row) in zip(spots, blocks_cells):
        cx = margin + 5.08 + bx
        for c, u, w, h, ox, oy, side in row:
            layout.append((c, u, snap(cx + ox), snap(margin + 5.08 + by + oy), side))
            cx += w
    for c, u, sx, sy, side in layout:
        g = geo[c['lib_id']][u]
        ref = c['ref']
        inst = c['stamp'] if u == 1 and c['stamp'] else uid(ref, 'unit', u, c['stamp'])
        x0, y0, x1, y1 = g['bbox']
        mode, top_ext, bottom_ext = side
        top_y, bot_y, mid_y = sy - y1 - top_ext, sy - y0 + bottom_ext, sy - (y1 + y0) / 2
        ref_at, val_at, rjust = {
            'tb': ((sx + x0, sy - y1 - 1.27), (sx + x0, sy - y0 + 2.54), False),
            'top': ((sx + x0, top_y - 3.81), (sx + x0, top_y - 1.27), False),
            'bottom': ((sx + x0, bot_y + 2.54), (sx + x0, bot_y + 5.08), False),
            'right': ((sx + x1 + 1.27, mid_y - 0.64), (sx + x1 + 1.27, mid_y + 1.91), False),
            'left': ((sx + x0 - 1.27, mid_y - 0.64), (sx + x0 - 1.27, mid_y + 1.91), True)}[mode]
        fields = [('Reference', ref, *ref_at, False), ('Value', c['value'], *val_at, False),
                  ('Footprint', c['footprint'], sx, sy, True), ('Datasheet', c['fields'].get('Datasheet', ''), sx, sy, True),
                  ('Description', c['fields'].get('Description', ''), sx, sy, True)]
        fields += [(k, v, sx, sy, True) for k, v in c['fields'].items() if k not in ('Footprint', 'Datasheet', 'Description', 'Reference', 'Value')]
        dnp = str(c['fields'].get('DNP', '')).lower() in ('1', 'yes', 'true', 'dnp')
        on_bom = not ref.startswith('#')
        lines = [f'(symbol (lib_id {q(c["lib_id"])}) (at {sx} {sy} 0) (unit {u})',
                 f'(exclude_from_sim no) (in_bom {"yes" if on_bom else "no"}) (on_board {"yes" if on_bom else "no"}) (dnp {"yes" if dnp else "no"})',
                 f'(uuid {q(inst)})']
        for k, v, fx, fy, hide in fields:
            just = '' if hide else (' (justify right)' if rjust else ' (justify left)')
            lines.append(f'(property {q(k)} {q(v)} (at {round(fx, 3)} {round(fy, 3)} 0) (effects (font (size {FONT} {FONT})){just}{" (hide yes)" if hide else ""}))')
        for num, *_ in g['pins']:
            lines.append(f'(pin {q(num)} (uuid {q(uid(inst, "pin", num))}))')
        lines.append(f'(instances (project {q(project)} (path {q("/" + root_uuid)} (reference {q(ref)}) (unit {u}))))')
        items.append('\n  '.join(lines) + ')')
        nc_pins = {x.strip() for x in str(c['fields'].get('NC_PINS', '')).split(',') if x.strip()}
        for num, pname, px, py, ang, ln, kind in g['pins']:
            ex, ey = round(sx + px, 4), round(sy - py, 4)
            net = pin_net.get((ref, num))
            if net is None and num in nc_pins:
                net = 'NC'           # declared "not connected" in the design code (SKiDL drops NC pins from netlists)
            d = OUTWARD.get(ang % 360, (-1, 0))
            if net is None or net.startswith('unconnected-') or net == 'NC':
                if kind == 'no_connect' or net is not None:
                    items.append(f'(no_connect (at {ex} {ey}) (uuid {q(uid(inst, "nc", num))}))')
                continue
            lx, ly = round(ex + d[0] * STUB, 4), round(ey + d[1] * STUB, 4)
            items.append(f'(wire (pts (xy {ex} {ey}) (xy {lx} {ly})) (stroke (width 0) (type default)) (uuid {q(uid(inst, "wire", num))}))')
            ang_l = LABEL_ANGLE[d]
            just = {0: 'left', 180: 'right', 90: 'left', 270: 'right'}[ang_l]
            # global labels: the board net is named exactly as in the design code (local labels would give "/NET")
            items.append(f'(global_label {q(net)} (shape passive) (at {lx} {ly} {ang_l}) (fields_autoplaced yes) '
                         f'(effects (font (size {FONT} {FONT})) (justify {just})) (uuid {q(uid(inst, "label", num))}) '
                         f'(property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {lx} {ly} 0) (effects (font (size {FONT} {FONT})) (hide yes))))')
    head = [f'(kicad_sch (version 20231120) (generator "pcbkit_sch_gen") (generator_version "{common.KIT_VERSION}")',
            f'(uuid {q(root_uuid)})', f'(paper {q(paper[0])})',
            f'(title_block (title {q(title)}) (rev {q(rev)}) (company {q(company)})',
            f'  (comment 1 {q("Generated from " + Path(net_path).name + " by pcbkit/sch_gen.py: edit the design code, not this file")}))',
            '(lib_symbols', *symbols.values(), ')']
    tail = [f'(sheet_instances (path "/" (page "1")))', ')']
    text = '\n'.join(head + items + tail) + '\n'
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / Path(out_path).name
        tmp.write_text(text, encoding='utf-8')
        for f in ('sym-lib-table', 'fp-lib-table'):
            if (Path(project_dir) / f).exists():
                (Path(d) / f).write_text((Path(project_dir) / f).read_text())
        common.kicad_cli('sch', 'upgrade', '--force', tmp)
        check = common.parse_netlist(common.export_netlist(tmp, Path(d) / 'check.xml'))
        want = {frozenset(m for m in ms if not m[0].startswith('#')) for n, ms in nets.items()}
        want = {s for s in want if s}
        got = {frozenset(ms) for n, ms in check['nets'].items() if not n.startswith('unconnected-')}
        if want != got:
            missing, extra = want - got, got - want
            raise SystemExit(f'generated schematic connectivity differs from the netlist: missing {[sorted(s) for s in missing][:5]}, '
                             f'unexpected {[sorted(s) for s in extra][:5]}')
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(tmp.read_bytes())
    pro = Path(out_path).with_suffix('.kicad_pro')
    if not pro.exists():   # without a project file kicad-cli ignores the project library tables
        pro.write_text('{\n  "meta": {\n    "filename": "%s",\n    "version": 3\n  }\n}\n' % pro.name)
    tables = common.ensure_lib_tables(Path(out_path).parent, {c['lib_id'].split(':')[0] for c in comps},
                                      {c['footprint'].split(':')[0] for c in comps if ':' in c['footprint']})
    return {'parts': len(comps), 'nets': len(nets), 'paper': paper[0], 'blocks': order, 'tables': tables}


def main():
    ap = argparse.ArgumentParser(description='Readable KiCad schematic from a netlist')
    ap.add_argument('netlist'); ap.add_argument('output')
    ap.add_argument('--title', default=''); ap.add_argument('--rev', default=''); ap.add_argument('--company', default='')
    ap.add_argument('--power-flag', action='append', default=[], help='net that gets a PWR_FLAG (driven by a connector)')
    ap.add_argument('--power-nets', default='GND,GND*,*GND,+*,-*,VBUS,VCC*,VDD*,VSS*,VBAT*,VSYS*,V3*,V5*',
                    help='net patterns treated as supplies when grouping parts into blocks')
    ap.add_argument('--drop-field', action='append', default=['SKiDL Line'])
    ap.add_argument('--project-dir', help='KiCad project directory (default: the output directory)')
    ap.add_argument('--normalize-input', action='store_true', help='strip dates and SKiDL line numbers from the input netlist file')
    a = ap.parse_args()
    if a.normalize_input:
        normalize_netlist(a.netlist)
    res = generate(a.netlist, a.output, a.title, a.rev, a.company, a.power_flag, a.power_nets.split(','), a.drop_field, Path(a.project_dir or Path(a.output).parent).resolve())
    print(f"{a.output}: {res['parts']} symbols, {res['nets']} nets, {res['paper']}; blocks: " + ' | '.join(' '.join(b) for b in res['blocks']))
    for t in res['tables']:
        print('  ' + t)


if __name__ == '__main__':
    main()
