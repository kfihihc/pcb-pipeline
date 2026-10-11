"""Compare two revisions of a board, and optionally hold a change to its declared scope.

Reports footprints added/removed/moved, library changes, pad copper, tracks, vias, zones, per-footprint
graphics and field values. With --allow-refs / --allow-nets (or --scope change.toml) it lists every
change outside the declared scope and exits 1: an agent's branch may touch only what its change note
names (see the pcb-pipeline change-control rules).

usage: board_diff.py OLD.kicad_pcb NEW.kicad_pcb [--json out.json]
                     [--allow-refs U1,C3] [--allow-nets VBUS,GND] [--scope docs/changes/0003.toml]
       old revision from git: git show main:hw/board.kicad_pcb > /tmp/old.kicad_pcb
"""
import argparse, collections, fnmatch, json, sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kicad_compat as kc  # noqa: E402

k = kc.pcbnew
NM = 1e6


def copper(p):
    out = []
    for layer in p.GetLayerSet().CuStack():
        poly = p.GetEffectivePolygon(layer, k.ERROR_INSIDE); bb = poly.BBox()
        out.append((k.LayerName(layer), bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom(), round(poly.Area())))
    return tuple(out), p.GetDrillSize().x, p.GetDrillSize().y


def graphics(fp):
    """Per-layer multiset of the footprint's own drawings (absolute coordinates, 1 um grid)."""
    out = collections.defaultdict(collections.Counter)
    for s in fp.GraphicalItems():
        s = s.Cast()
        if not isinstance(s, k.PCB_SHAPE):
            continue
        poly = k.SHAPE_POLY_SET(); s.TransformShapeToPolygon(poly, s.GetLayer(), 0, 1000, k.ERROR_OUTSIDE)
        bb = poly.BBox()
        out[k.LayerName(s.GetLayer())][(round(bb.GetLeft(), -3), round(bb.GetTop(), -3), round(bb.GetRight(), -3),
                                        round(bb.GetBottom(), -3), round(poly.Area(), -6))] += 1
    return out


def snapshot(path):
    b = kc.load_board(path)
    fps, pads, gfx, fields = {}, collections.Counter(), {}, {}
    for f in b.GetFootprints():
        r = f.GetReference()
        fps[r] = (f.GetFPID().GetUniStringLibId(), f.GetX(), f.GetY(), round(f.GetOrientation().AsDegrees(), 3),
                  f.IsFlipped(), f.IsLocked())
        for p in f.Pads():
            pads[(r, p.GetNumber(), copper(p), p.GetNetname(), p.GetLocalZoneConnection())] += 1
        gfx[r] = graphics(f)
        fields[r] = {g.GetName(): g.GetText() for g in f.GetFields()}
    tracks, vias = collections.Counter(), collections.Counter()
    for t in b.GetTracks():
        if kc.is_via(t):
            vias[(t.GetX(), t.GetY(), t.GetWidth(k.F_Cu), t.GetDrill(), t.GetNetname(), t.IsLocked())] += 1
        else:
            e = sorted([(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)])
            tracks[(k.LayerName(t.GetLayer()), tuple(e), t.GetWidth(), t.GetNetname(), t.IsLocked())] += 1
    zones = {}
    for z in b.Zones():
        for l in z.GetLayerSet().Seq():
            fill = z.GetFilledPolysList(l).Area() / NM ** 2 if z.HasFilledPolysForLayer(l) else 0.0
            zones[(z.GetZoneName() or z.GetNetname(), k.LayerName(l))] = (round(z.Outline().Area() / NM ** 2, 3), round(fill, 3), z.GetNetname())
    edge = sorted((round(s.GetStart().x, -3), round(s.GetStart().y, -3), round(s.GetEnd().x, -3), round(s.GetEnd().y, -3))
                  for s in b.GetDrawings() if s.GetLayer() == k.Edge_Cuts and isinstance(s, k.PCB_SHAPE))
    return dict(fps=fps, pads=pads, gfx=gfx, fields=fields, tracks=tracks, vias=vias, zones=zones, edge=edge,
                rev=b.GetTitleBlock().GetRevision())


def diff(a, b):
    out = {'revision': [a['rev'], b['rev']]}
    out['footprints_added'] = sorted(set(b['fps']) - set(a['fps']))
    out['footprints_removed'] = sorted(set(a['fps']) - set(b['fps']))
    common = sorted(set(a['fps']) & set(b['fps']))
    out['lib_id_changed'] = {r: [a['fps'][r][0], b['fps'][r][0]] for r in common if a['fps'][r][0] != b['fps'][r][0]}
    out['moved_or_rotated'] = sorted(r for r in common if a['fps'][r][1:5] != b['fps'][r][1:5])
    out['lock_changed'] = sorted(r for r in common if a['fps'][r][5] != b['fps'][r][5])
    pa, pb = a['pads'] - b['pads'], b['pads'] - a['pads']
    out['pads'] = {'total': sum(b['pads'].values()), 'removed_or_changed': sum(pa.values()), 'added_or_changed': sum(pb.values()),
                   'refs': sorted({key[0] for key in pa + pb})}
    for kind in ('tracks', 'vias'):
        rem, add = a[kind] - b[kind], b[kind] - a[kind]
        out[kind] = {'total': sum(b[kind].values()), 'removed': sum(rem.values()), 'added': sum(add.values()),
                     'nets': sorted({key[-2] for key in rem + add}),
                     'locked_changed': sum(n for key, n in (rem + add).items() if key[-1])}
    layers = collections.defaultdict(list)
    for r in common:
        for layer in set(a['gfx'][r]) | set(b['gfx'][r]):
            if a['gfx'][r].get(layer) != b['gfx'][r].get(layer):
                layers[layer].append(r)
    out['footprint_graphics_changed'] = {layer: sorted(refs) for layer, refs in sorted(layers.items())}
    out['field_values_changed'] = sorted(f'{r}.{n}' for r in common for n in set(a['fields'][r]) | set(b['fields'][r])
                                         if a['fields'][r].get(n) != b['fields'][r].get(n))
    out['zones'] = {f'{n} {l}': {'outline_mm2': [a['zones'].get((n, l), (0, 0, ''))[0], v[0]],
                                 'fill_mm2': [a['zones'].get((n, l), (0, 0, ''))[1], v[1]], 'net': v[2]}
                    for (n, l), v in sorted(b['zones'].items()) if a['zones'].get((n, l)) != v}
    out['zones_removed'] = sorted(f'{n} {l}' for (n, l) in set(a['zones']) - set(b['zones']))
    out['board_outline_changed'] = a['edge'] != b['edge']
    return out


def match(name, patterns):
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def out_of_scope(d, refs, nets):
    """Changes that touch neither an allowed reference nor an allowed net."""
    bad = []
    for key in ('footprints_added', 'footprints_removed', 'moved_or_rotated', 'lock_changed'):
        bad += [f'{key}: {r}' for r in d[key] if not match(r, refs)]
    bad += [f'lib_id_changed: {r}' for r in d['lib_id_changed'] if not match(r, refs)]
    bad += [f'pads: {r}' for r in d['pads']['refs'] if not match(r, refs)]
    for kind in ('tracks', 'vias'):
        bad += [f'{kind}: net {n}' for n in d[kind]['nets'] if not match(n, nets)]
        if d[kind]['locked_changed'] and '*' not in nets:
            bad.append(f"{kind}: {d[kind]['locked_changed']} locked items changed (unlock them in the change note first)")
    bad += [f'zone: {z}' for z, v in d['zones'].items() if not match(v['net'], nets) and v['outline_mm2'][0] != v['outline_mm2'][1]]
    bad += [f'zone removed: {z}' for z in d['zones_removed']]
    fields = collections.defaultdict(list)
    for f in d['field_values_changed']:
        ref, _, name = f.partition('.')
        if not match(ref, refs):
            fields[name].append(ref)
    bad += [f'field {name}: {len(r)} parts ({", ".join(r[:6])}{" ..." if len(r) > 6 else ""})' for name, r in sorted(fields.items())]
    for layer, rs in d['footprint_graphics_changed'].items():
        out = [r for r in rs if not match(r, refs)]
        if out:
            bad.append(f'{layer} graphics: {len(out)} parts ({", ".join(out[:6])}{" ..." if len(out) > 6 else ""})')
    if d['board_outline_changed'] and 'Edge.Cuts' not in refs:
        bad.append('board outline changed (add "Edge.Cuts" to the allowed refs)')
    return bad


def main():
    ap = argparse.ArgumentParser(description='Compare two board revisions; optionally enforce a change scope')
    ap.add_argument('old'); ap.add_argument('new'); ap.add_argument('--json')
    ap.add_argument('--allow-refs', default=''); ap.add_argument('--allow-nets', default=''); ap.add_argument('--scope')
    a = ap.parse_args()
    d = diff(snapshot(a.old), snapshot(a.new))
    refs = [r for r in a.allow_refs.split(',') if r]
    nets = [n for n in a.allow_nets.split(',') if n]
    if a.scope:
        s = tomllib.loads(Path(a.scope).read_text(encoding='utf-8')).get('scope', {})
        refs += s.get('refs', []); nets += s.get('nets', [])
    if refs or nets or a.scope:
        d['out_of_scope'] = out_of_scope(d, refs, nets)
    text = json.dumps(d, indent=1, ensure_ascii=False)
    if a.json:
        Path(a.json).write_text(text + '\n')
    print(text)
    return 1 if d.get('out_of_scope') else 0


if __name__ == '__main__':
    sys.exit(main())
