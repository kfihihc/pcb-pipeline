"""Create or update the board's outline, copper layer count, title block, fabrication minimums and net
classes from layout/board.toml, so these decisions live in reviewed text rather than GUI clicks.

  [board]
  layers = 2                          # copper layers
  thickness_mm = 1.6
  outline = { shape = "rect", width = 30, height = 20, corner_radius = 1.0, origin = [100, 100] }

  [rules]                             # fabrication minimums (board setup > constraints)
  min_track_width = 0.127
  min_clearance = 0.127
  min_via_diameter = 0.6
  min_through_hole = 0.3
  min_hole_to_hole = 0.5
  min_copper_edge_clearance = 0.3

  [[netclass]]                        # "Default" sets the default class
  name = "Default"
  track_width = 0.25
  clearance = 0.2
  via_diameter = 0.6
  via_drill = 0.3

  [[netclass]]
  name = "POWER"
  track_width = 0.5
  clearance = 0.2
  via_diameter = 0.8
  via_drill = 0.4
  patterns = ["VBUS", "+3V3", "GND"]

  [[zone]]                            # copper pours, replaced on every run (refill afterwards)
  name = "GND pour"
  net = "GND"
  layers = ["F.Cu", "B.Cu"]
  clearance = 0.25
  min_width = 0.25
  priority = 0
  thermal_gap = 0.5
  thermal_spoke = 0.4

  [[keepout]]                         # rule areas that routers (KiCadRoutingTools, Freerouting) also respect,
  name = "J1 no vias"                 # unlike custom .kicad_dru rules, which only KiCad's DRC reads
  around = "J1"                       # footprint courtyard bounding box (or rect = [x0, y0, x1, y1] in outline mm)
  margin = 0.2
  layers = ["F.Cu", "B.Cu"]
  no_vias = true                      # also: no_tracks, no_pours, no_pads, no_footprints

An existing outline is replaced only with --outline. Zones need their net on the board (run sync_pcb.py
first). Title block fields come from pcb.toml [project]. Refill zones afterwards:
kicad-cli pcb drc --refill-zones --save-board <board>  (in-process filling is broken in KiCad 10).
usage: python3 pcbkit/board_setup.py [--config pcb.toml] [--outline]
"""
import argparse, json, math, sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import kicad_compat as kc  # noqa: E402

k = kc.pcbnew
RULE_KEYS = {'min_track_width': 'min_track_width', 'min_clearance': 'min_clearance', 'min_via_diameter': 'min_via_diameter',
             'min_through_hole': 'min_through_hole_diameter', 'min_hole_to_hole': 'min_hole_to_hole',
             'min_copper_edge_clearance': 'min_copper_edge_clearance', 'min_hole_clearance': 'min_hole_clearance',
             'min_annular_width': 'min_via_annular_width', 'min_silk_clearance': 'min_silk_clearance'}


def outline(board, spec):
    for d in list(board.GetDrawings()):
        if d.GetLayer() == k.Edge_Cuts:
            board.Remove(d)
    if spec.get('shape', 'rect') != 'rect':
        raise SystemExit('only rect outlines are generated; draw other shapes in KiCad or import a DXF')
    x0, y0 = spec.get('origin', [100, 100])
    w, h, r = spec['width'], spec['height'], spec.get('corner_radius', 0)
    mm = k.FromMM

    def seg(a, b):
        s = k.PCB_SHAPE(board); s.SetShape(k.SHAPE_T_SEGMENT); s.SetLayer(k.Edge_Cuts); s.SetWidth(mm(0.05))
        s.SetStart(k.VECTOR2I(mm(a[0]), mm(a[1]))); s.SetEnd(k.VECTOR2I(mm(b[0]), mm(b[1]))); board.Add(s)

    def arc(c, start_deg):
        s = k.PCB_SHAPE(board); s.SetShape(k.SHAPE_T_ARC); s.SetLayer(k.Edge_Cuts); s.SetWidth(mm(0.05))
        a0, a1, am = math.radians(start_deg), math.radians(start_deg + 90), math.radians(start_deg + 45)
        pt = lambda a: k.VECTOR2I(mm(c[0] + r * math.cos(a)), mm(c[1] + r * math.sin(a)))
        s.SetArcGeometry(pt(a0), pt(am), pt(a1)); board.Add(s)

    seg((x0 + r, y0), (x0 + w - r, y0)); seg((x0 + w, y0 + r), (x0 + w, y0 + h - r))
    seg((x0 + w - r, y0 + h), (x0 + r, y0 + h)); seg((x0, y0 + h - r), (x0, y0 + r))
    if r:
        arc((x0 + w - r, y0 + r), 270); arc((x0 + w - r, y0 + h - r), 0); arc((x0 + r, y0 + h - r), 90); arc((x0 + r, y0 + r), 180)


def zones(board, specs):
    done, skipped = [], []
    bb = board.GetBoardEdgesBoundingBox()
    for spec in specs:
        for z in list(board.Zones()):
            if z.GetZoneName() == spec['name']:
                board.Remove(z)
        net = board.FindNet(spec['net'])
        if net is None or not bb.GetWidth():
            skipped.append(spec['name']); continue
        z = k.ZONE(board)
        ls = k.LSET()
        for name in spec['layers']:
            ls.AddLayer(board.GetLayerID(name))
        z.SetLayerSet(ls)
        z.SetNetCode(net.GetNetCode())
        z.SetZoneName(spec['name'])
        z.SetLocalClearance(k.FromMM(spec.get('clearance', 0.25)))
        z.SetMinThickness(k.FromMM(spec.get('min_width', 0.25)))
        z.SetAssignedPriority(spec.get('priority', 0))
        z.SetPadConnection(k.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(k.FromMM(spec.get('thermal_gap', 0.5)))
        z.SetThermalReliefSpokeWidth(k.FromMM(spec.get('thermal_spoke', 0.4)))
        o = z.Outline(); o.NewOutline()
        for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()), (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
            o.Append(x, y)
        board.Add(z)
        done.append(spec['name'])
    return done, skipped


def keepouts(board, specs):
    done, skipped = [], []
    edge = board.GetBoardEdgesBoundingBox()
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    for spec in specs:
        for z in list(board.Zones()):
            if z.GetIsRuleArea() and z.GetZoneName() == spec['name']:
                board.Remove(z)
        m = k.FromMM(spec.get('margin', 0))
        if 'around' in spec:
            f = fps.get(spec['around'])
            if f is None:
                skipped.append(spec['name']); continue
            bb = f.GetCourtyard(k.B_CrtYd if f.IsFlipped() else k.F_CrtYd).BBox()
            x0, y0, x1, y1 = bb.GetLeft() - m, bb.GetTop() - m, bb.GetRight() + m, bb.GetBottom() + m
        else:
            r = [k.FromMM(v) for v in spec['rect']]
            ox, oy = kc.outline_origin(board)
            x0, y0, x1, y1 = ox + r[0], oy + r[1], ox + r[2], oy + r[3]
        z = k.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetZoneName(spec['name'])
        ls = k.LSET()
        for name in spec.get('layers', ['F.Cu', 'B.Cu']):
            ls.AddLayer(board.GetLayerID(name))
        z.SetLayerSet(ls)
        z.SetDoNotAllowVias(spec.get('no_vias', False)); z.SetDoNotAllowTracks(spec.get('no_tracks', False))
        z.SetDoNotAllowZoneFills(spec.get('no_pours', False)); z.SetDoNotAllowPads(spec.get('no_pads', False))
        z.SetDoNotAllowFootprints(spec.get('no_footprints', False))
        o = z.Outline(); o.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            o.Append(int(x), int(y))
        board.Add(z)
        done.append(spec['name'])
    return done, skipped


def patch_project(pro, cfg):
    data = json.loads(pro.read_text())
    rules = data.setdefault('board', {}).setdefault('design_settings', {}).setdefault('rules', {})
    for key, value in cfg.get('rules', {}).items():
        rules[RULE_KEYS.get(key, key)] = value
    ns = data.setdefault('net_settings', {})
    classes = ns.setdefault('classes', [])
    patterns = [p for p in ns.get('netclass_patterns', []) or [] if p.get('netclass') not in {c['name'] for c in cfg.get('netclass', [])}]
    template = next((c for c in classes if c.get('name') == 'Default'), {})
    for i, nc in enumerate(cfg.get('netclass', [])):
        cur = next((c for c in classes if c.get('name') == nc['name']), None)
        if cur is None:
            cur = dict(template, name=nc['name'], priority=i); classes.append(cur)
        for key in ('track_width', 'clearance', 'via_diameter', 'via_drill', 'diff_pair_width', 'diff_pair_gap'):
            if key in nc:
                cur[key] = nc[key]
        patterns += [{'netclass': nc['name'], 'pattern': p} for p in nc.get('patterns', [])]
    ns['netclass_patterns'] = patterns
    pro.write_text(json.dumps(data, indent=2) + '\n')


def main():
    ap = argparse.ArgumentParser(description='Create or update board outline, layers and rules')
    ap.add_argument('--config'); ap.add_argument('--board-config', default='layout/board.toml')
    ap.add_argument('--outline', action='store_true', help='replace an existing outline')
    a = ap.parse_args()
    p = common.Project(a.config)
    cfg = tomllib.loads((p.root / a.board_config).read_text(encoding='utf-8'))
    new = not p.pcb.exists()
    p.pcb.parent.mkdir(parents=True, exist_ok=True)
    b = k.CreateEmptyBoard() if new else kc.load_board(p.pcb)
    bc = cfg.get('board', {})
    b.SetCopperLayerCount(bc.get('layers', 2))
    if 'thickness_mm' in bc:
        b.GetDesignSettings().SetBoardThickness(k.FromMM(bc['thickness_mm']))
    if new or a.outline:
        outline(b, bc['outline'])
    made, skipped = zones(b, cfg.get('zone', []))
    kmade, kskipped = keepouts(b, cfg.get('keepout', []))
    made += kmade; skipped += kskipped
    proj = p.section('project')
    tb = b.GetTitleBlock()
    tb.SetTitle(proj.get('title', p.name)); tb.SetRevision(str(proj.get('revision', '')))
    if proj.get('company'):
        tb.SetCompany(proj['company'])
    if proj.get('license'):
        tb.SetComment(0, f"License: {proj['license']}")
    pro = p.pcb.with_suffix('.kicad_pro')
    before = json.loads(pro.read_text()) if pro.exists() else None
    k.SaveBoard(str(p.pcb), b)                  # also writes the project file; keep its non-board sections
    if before is not None:
        after = json.loads(pro.read_text())
        before['board'] = after.get('board', before.get('board', {}))
        pro.write_text(json.dumps(before, indent=2) + '\n')
    patch_project(pro, cfg)
    print(('created ' if new else 'updated ') + p.rel(p.pcb) + (f'; zones and keepouts {made}' if made else '')
          + (f'; skipped (net or footprint not on the board yet, run sync_pcb.py first): {skipped}' if skipped else ''))


if __name__ == '__main__':
    main()
