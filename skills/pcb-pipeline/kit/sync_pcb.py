"""Update the board from the schematic, deterministically: the scripted equivalent of KiCad's
"Update PCB from Schematic", so code-first designs (SKiDL, generators) reach the board without the GUI.

Footprints are matched to symbols by symbol path (UUID), then by reference. For each symbol:
  - missing footprint: loaded from the library tables and parked in a staging grid right of the board
    outline (or placed from --placement, see place.py);
  - existing footprint: reference, value, fields (hidden, Fab layer), path, DNP / BOM / position-file
    attributes and pad nets are updated; position, rotation, side, lock state and routing are kept;
  - footprint library ID changed: reported; replaced only with --swap (position and side kept, pad nets
    reassigned; tracks on the old pads may then fail DRC, which the gate reports).
Footprints without a symbol are reported, and removed only with --remove-extra (board-only items such
as logos and mounting holes are kept when marked "not in schematic").

usage: python3 pcbkit/sync_pcb.py [--config pcb.toml] [--dry-run] [--swap] [--remove-extra] [--json report.json]
Afterwards: python3 pcbkit/gate.py --only drc  (schematic parity must be clean).
"""
import argparse, json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import kicad_compat as kc  # noqa: E402

k = kc.pcbnew
SKIP_FIELDS = {'Reference', 'Value', 'Footprint'}
IO = k.PCB_IO_MGR.FindPlugin(k.PCB_IO_MGR.KICAD_SEXP)


def load_fp(fpid, root, table):
    lib, _, name = fpid.partition(':')
    if lib not in table:
        raise KeyError(f'footprint library {lib} is not in the library tables')
    fp = IO.FootprintLoad(str(table[lib]), name)
    if fp is None:
        raise KeyError(f'footprint {fpid} not found in {table[lib]}')
    fp.SetFPID(k.LIB_ID(lib, name))
    return fp


def set_fields(fp, comp):
    changed = 0
    if fp.GetReference() != comp['ref']:
        fp.SetReference(comp['ref']); changed += 1
    if fp.GetValue() != comp['value']:
        fp.SetValue(comp['value']); changed += 1
    value = fp.GetField(k.FIELD_T_VALUE)
    for name, text in comp['fields'].items():
        if name in SKIP_FIELDS:
            continue
        if fp.HasField(name):
            g = fp.GetField(name)
            if g.GetText() != text:
                g.SetText(text); changed += 1
            continue
        g = k.PCB_FIELD(fp, k.FIELD_T_USER, name); g.SetOrdinal(fp.GetNextFieldOrdinal())
        g.SetAttributes(value); g.SetText(text); g.SetVisible(False)
        g.SetLayer(k.B_Fab if fp.IsFlipped() else k.F_Fab); g.SetPosition(fp.GetPosition())
        fp.Add(g); changed += 1
    if comp['path'] and fp.GetPath().AsString() != comp['path']:
        fp.SetPath(k.KIID_PATH(comp['path'])); changed += 1
    if (fp.GetSheetname(), fp.GetSheetfile()) != (comp['sheetname'], comp['sheetfile']):
        fp.SetSheetname(comp['sheetname']); fp.SetSheetfile(comp['sheetfile']); changed += 1
    for getter, setter, want in (('IsDNP', 'SetDNP', comp['dnp']),
                                 ('IsExcludedFromBOM', 'SetExcludedFromBOM', comp['exclude_from_bom'])):
        if getattr(fp, getter)() != want:
            getattr(fp, setter)(want); changed += 1
    return changed


def staging(board):
    bb = board.GetBoardEdgesBoundingBox()
    x0 = (bb.GetRight() if bb.GetWidth() else 0) + k.FromMM(10)
    y0 = bb.GetTop() if bb.GetHeight() else 0
    n = 0
    while True:
        yield k.VECTOR2I(x0 + k.FromMM(6) * (n % 8), y0 + k.FromMM(6) * (n // 8))
        n += 1


def sync(project, dry_run=False, swap=False, remove_extra=False):
    with tempfile.TemporaryDirectory() as d:
        netlist = common.parse_netlist(common.export_netlist(project.sch, Path(d) / 'n.xml', cwd=project.root))
    by_pin = common.pin_to_net(netlist)
    table = common.lib_table('fp', project.kicad_dir)
    pro_text = project.pro.read_text() if project.pro and project.pro.exists() else None
    b = kc.load_board(project.pcb)
    fps = list(b.GetFootprints())
    by_path = {f.GetPath().AsString(): f for f in fps if f.GetPath().AsString()}
    by_ref = {f.GetReference(): f for f in fps}
    report = {'added': [], 'updated': {}, 'lib_changed': {}, 'swapped': [], 'extra': [], 'removed': [], 'nets_set': 0}
    park = staging(b)
    used = set()                                   # footprint UUIDs matched to a symbol
    nets = {common.unescape(nt.GetNetname()): nt for nt in b.GetNetInfo().NetsByName().values()}
    keep_alive = []
    for ref, c in sorted(netlist['components'].items()):
        if c['exclude_from_board']:
            continue
        c = dict(c, ref=ref)
        fp = by_path.get(c['path']) or by_ref.get(ref)
        if fp is not None and fp.GetFPID().GetUniStringLibId() != c['footprint']:
            report['lib_changed'][ref] = [fp.GetFPID().GetUniStringLibId(), c['footprint']]
            if swap and not dry_run:
                new = load_fp(c['footprint'], project.root, table)
                b.Add(new)
                if fp.IsFlipped():
                    new.Flip(new.GetPosition(), k.FLIP_DIRECTION_TOP_BOTTOM)
                new.SetOrientation(fp.GetOrientation()); new.SetPosition(fp.GetPosition()); new.SetLocked(fp.IsLocked())
                b.Remove(fp); keep_alive.append(fp)
                fp = new
                report['swapped'].append(ref)
        if fp is None:
            report['added'].append(ref)
            if dry_run:
                continue
            fp = load_fp(c['footprint'], project.root, table)
            b.Add(fp)
            fp.SetPosition(next(park))
        used.add(fp.m_Uuid.AsString())
        if dry_run:
            continue
        n = set_fields(fp, c)
        for p in fp.Pads():
            net_name = by_pin.get((ref, p.GetNumber()))
            if net_name is None:
                if p.GetNetname():
                    p.SetNetCode(0); n += 1
                continue
            net = nets.get(net_name)
            if net is None:
                net = k.NETINFO_ITEM(b, common.board_net_name(net_name)); b.Add(net); nets[net_name] = net
            if common.unescape(p.GetNetname()) != net_name:
                p.SetNet(net); n += 1; report['nets_set'] += 1
        if n and ref not in report['added']:
            report['updated'][ref] = n
    for f in list(b.GetFootprints()):
        if f.m_Uuid.AsString() in used:
            continue
        if f.GetAttributes() & k.FP_BOARD_ONLY:
            continue
        report['extra'].append(f.GetReference())
        if remove_extra and not dry_run:
            b.Remove(f); keep_alive.append(f); report['removed'].append(f.GetReference())
    if not dry_run:
        b.BuildConnectivity()
        k.SaveBoard(str(project.pcb), b)
        if pro_text is not None:          # pcbnew rewrites the project file on save; keep the committed one
            project.pro.write_text(pro_text)
    return report


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Update the board from the schematic')
    ap.add_argument('--config'); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--swap', action='store_true'); ap.add_argument('--remove-extra', action='store_true'); ap.add_argument('--json')
    a = ap.parse_args()
    p = common.Project(a.config)
    if not p.pcb.exists():
        sys.exit(f'{p.pcb} does not exist: create it with pcbkit/new_board.py (outline, stackup, rules) first')
    rep = sync(p, a.dry_run, a.swap, a.remove_extra)
    if a.json:
        common.write_json(a.json, rep)
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    sys.exit(1 if (rep['extra'] and not a.remove_extra) or (rep['lib_changed'] and not a.swap) else 0)
