"""Declarative layout metrics: the project's own review rules, measured on the board and held to
thresholds. They catch what DRC does not (a track on the ground plane, a switching node made thin,
a decoupling capacitor that drifted away, a USB pair that wanders).

Each [[metric]] in checks/metrics.toml has an id, a kind with its parameters, at most one value
check (eq / min / max / approx+tol / keys_subset / each_max / each_min) and a `why`. Kinds:

  tracks_on_layer      layer                       number of track segments on a layer
  track_count          [layer] [net]               number of track segments
  via_count            [net]                       number of vias
  net_length_mm        net | nets, [sum]           routed track length (sum = true: one total for all nets)
  net_vias             net | nets                  vias on the net
  net_layers           net | nets                  sorted copper layers the net's tracks use
  min_track_width_mm   net | nets, [ignore_shorter_mm]  narrowest track (neck-downs shorter than the limit ignored)
  pad_distance_mm      a, b ("U1.1")               centre-to-centre distance of two pads
  decoupling_mm        pin ("U1.2"), cap ("C20")   pin to the nearest same-net pad of the capacitor
  vias_in_pad          pad ("U1.57")               same-net vias inside the pad + plated holes of that pad number
  via_sizes            -                           {"diameter/drill": count} in mm
  items_in_area        area, allow_nets            foreign tracks and vias inside a named rule area
  footprint_sides      -                           {"F": count, "B": count}
  zone_area_mm2        net, layer                  filled copper area of the net's zones on a layer
  zone_islands         net, layer                  separate filled polygons (a split plane shows up here)
  length_skew_mm       nets = [p, n]               routed length difference of a pair
  moved_from           anchors (JSON), tolerance_mm, [origin]   parts farther than tolerance from an anchor
  script               path, [function], key       a value from a project script's run(board_path) dict

usage: python3 pcbkit/metrics.py [--config pcb.toml] [--board other.kicad_pcb] [--json out.json]
"""
import argparse, collections, importlib.util, json, math, sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Project, write_json  # noqa: E402

CHECKS = ('eq', 'min', 'max', 'approx', 'keys_subset', 'each_max', 'each_min')


class Board:
    def __init__(self, path):
        import kicad_compat as kc
        self.k, self.kc = kc.pcbnew, kc
        self.b = kc.load_board(path)
        self.path = Path(path)
        self.fps = {f.GetReference(): f for f in self.b.GetFootprints()}
        self.tracks = kc.tracks(self.b)
        self.vias = kc.vias(self.b)

    mm = staticmethod(lambda v: v / 1e6)

    def layer(self, name):
        lid = self.b.GetLayerID(name)
        if lid < 0:
            raise KeyError(f'unknown layer {name}')
        return lid

    def pad(self, spec):
        ref, _, num = spec.partition('.')
        if ref not in self.fps:
            raise KeyError(f'no footprint {ref}')
        pads = [p for p in self.fps[ref].Pads() if p.GetNumber() == num]
        if not pads:
            raise KeyError(f'no pad {spec}')
        def area(p):
            bb = p.GetBoundingBox()
            return bb.GetWidth() * bb.GetHeight()
        return max(pads, key=area)     # an exposed pad split into several pads: the main one

    def xy(self, item):
        p = item.GetPosition()
        return self.mm(p.x), self.mm(p.y)


def per_net(fn, spec):
    if 'nets' in spec:
        return {n: fn(n) for n in spec['nets']}
    return fn(spec['net'])


def measure(B, spec, scripts):
    k, mm, kind = B.k, B.mm, spec['kind']
    T = B.tracks
    if kind == 'tracks_on_layer':
        lid = B.layer(spec['layer'])
        return sum(1 for t in T if t.GetLayer() == lid)
    if kind == 'track_count':
        lid = B.layer(spec['layer']) if 'layer' in spec else None
        return sum(1 for t in T if (lid is None or t.GetLayer() == lid) and ('net' not in spec or t.GetNetname() == spec['net']))
    if kind == 'via_count':
        return sum(1 for v in B.vias if 'net' not in spec or v.GetNetname() == spec['net'])
    if kind == 'net_length_mm':
        v = per_net(lambda n: round(sum(mm(t.GetLength()) for t in T if t.GetNetname() == n), 3), spec)
        return round(sum(v.values()), 3) if spec.get('sum') and isinstance(v, dict) else v
    if kind == 'net_vias':
        return per_net(lambda n: sum(1 for v in B.vias if v.GetNetname() == n), spec)
    if kind == 'net_layers':
        return per_net(lambda n: sorted({B.b.GetLayerName(t.GetLayer()) for t in T if t.GetNetname() == n}), spec)
    if kind == 'min_track_width_mm':
        short = spec.get('ignore_shorter_mm', 0)      # neck-downs into fine-pitch pads
        def width(n):
            w = [mm(t.GetWidth()) for t in T if t.GetNetname() == n and mm(t.GetLength()) >= short]
            return round(min(w), 4) if w else None
        return per_net(width, spec)
    if kind == 'pad_distance_mm':
        return round(math.dist(B.xy(B.pad(spec['a'])), B.xy(B.pad(spec['b']))), 3)
    if kind == 'decoupling_mm':
        p = B.pad(spec['pin'])
        cands = [q for q in B.fps[spec['cap']].Pads() if q.GetNetname() == p.GetNetname()]
        if not cands:
            raise KeyError(f"{spec['cap']} has no pad on net {p.GetNetname()}")
        return round(min(math.dist(B.xy(p), B.xy(q)) for q in cands), 3)
    if kind == 'vias_in_pad':
        ref, _, num = spec['pad'].partition('.')
        pads = [p for p in B.fps[ref].Pads() if p.GetNumber() == num]
        main = B.pad(spec['pad'])
        bb = main.GetBoundingBox()
        free = sum(1 for v in B.vias if bb.Contains(v.GetPosition()) and v.GetNetname() == main.GetNetname())
        return free + sum(1 for p in pads if p.GetAttribute() == k.PAD_ATTRIB_PTH)
    if kind == 'via_sizes':
        c = collections.Counter((round(mm(v.GetWidth(k.F_Cu)), 3), round(mm(v.GetDrill()), 3)) for v in B.vias)
        return {f'{d:g}/{h:g}': n for (d, h), n in sorted(c.items())}
    if kind == 'items_in_area':
        areas = [z for z in B.b.Zones() if z.GetIsRuleArea() and z.GetZoneName() == spec['area']]
        if not areas:
            raise KeyError(f"no rule area named {spec['area']}")
        allow = set(spec.get('allow_nets', []))
        def inside(pt): return any(z.Outline().Contains(pt) for z in areas)
        n = 0
        for t in B.b.GetTracks():
            if t.GetNetname() in allow:
                continue
            if B.kc.is_via(t):
                n += inside(t.GetPosition())
            else:
                n += inside(t.GetStart()) or inside(t.GetEnd())
        return n
    if kind == 'footprint_sides':
        c = collections.Counter('B' if f.IsFlipped() else 'F' for f in B.fps.values())
        return {'F': c.get('F', 0), 'B': c.get('B', 0)}
    if kind in ('zone_area_mm2', 'zone_islands'):
        lid = B.layer(spec['layer'])
        zones = [z for z in B.b.Zones() if not z.GetIsRuleArea() and z.GetNetname() == spec['net'] and z.HasFilledPolysForLayer(lid)]
        polys = [z.GetFilledPolysList(lid) for z in zones]
        if kind == 'zone_area_mm2':
            return round(sum(p.Area() for p in polys) / 1e12, 3)
        return sum(p.OutlineCount() for p in polys)
    if kind == 'length_skew_mm':
        a, b = (sum(mm(t.GetLength()) for t in T if t.GetNetname() == n) for n in spec['nets'])
        return round(abs(a - b), 3)
    if kind == 'moved_from':
        anchors = json.loads((B.root / spec['anchors']).read_text())
        ox, oy = spec.get('origin', [0, 0])
        moved = {}
        for ref, a in anchors.items():
            if ref in B.fps:
                x, y = B.xy(B.fps[ref])
                d = math.dist((x - ox, y - oy), tuple(a[:2] if isinstance(a, list) else a['center']))
                if d > spec.get('tolerance_mm', 0.5):
                    moved[ref] = round(d, 2)
        return moved
    if kind == 'script':
        path = B.root / spec['path']
        if path not in scripts:
            mod_spec = importlib.util.spec_from_file_location(path.stem, path)
            mod = importlib.util.module_from_spec(mod_spec)
            sys.path.insert(0, str(path.parent))
            mod_spec.loader.exec_module(mod)
            scripts[path] = json.loads(json.dumps(getattr(mod, spec.get('function', 'run'))(B.path)))
        v = scripts[path]
        for key in spec['key'].split('.') if spec.get('key') else []:
            v = v[key]
        return v
    raise KeyError(f'unknown metric kind {kind}')


def judge(spec, v):
    bad = []
    if 'eq' in spec and v != spec['eq']:
        bad.append(f"= {v}, expected {spec['eq']}")
    if 'approx' in spec and (v is None or abs(v - spec['approx']) > spec.get('tol', 1e-6)):
        bad.append(f"= {v}, expected {spec['approx']} ± {spec.get('tol', 1e-6)}")
    if 'min' in spec and (v is None or v < spec['min']):
        bad.append(f"= {v} < {spec['min']}")
    if 'max' in spec and (v is None or v > spec['max']):
        bad.append(f"= {v} > {spec['max']}")
    if 'keys_subset' in spec and set(v) - set(spec['keys_subset']):
        bad.append(f"new keys {sorted(set(v) - set(spec['keys_subset']))}")
    for key, lim in spec.get('each_max', {}).items():
        x = v.get(key) if isinstance(v, dict) else None
        x = x[-1] if isinstance(x, (list, tuple)) else x
        if x is None or x > lim + spec.get('tol', 0):
            bad.append(f'{key} = {x} > {lim}')
    for key, lim in spec.get('each_min', {}).items():
        x = v.get(key) if isinstance(v, dict) else None
        x = x[-1] if isinstance(x, (list, tuple)) else x
        if x is None or x < lim - spec.get('tol', 0):
            bad.append(f'{key} = {x} < {lim}')
    return bad


def evaluate(project, board=None, config=None):
    """Return (values {id: value}, failures [str], rules [spec])."""
    cfg_file = Path(config) if config else project.path(project.section('gate').get('metrics', 'checks/metrics.toml'))
    rules = tomllib.loads(cfg_file.read_text(encoding='utf-8')).get('metric', [])
    B = Board(board or project.pcb)
    B.root = project.root
    values, failures, scripts = {}, [], {}
    seen = set()
    for spec in rules:
        mid = spec['id']
        if mid in seen:
            failures.append(f'{mid}: duplicate id'); continue
        seen.add(mid)
        if not spec.get('why'):
            failures.append(f'{mid}: missing why')
        try:
            v = measure(B, spec, scripts)
        except Exception as e:  # a metric that cannot be measured is a failed metric
            values[mid] = None
            failures.append(f'{mid}: {type(e).__name__}: {e}')
            continue
        values[mid] = v
        failures += [f'{mid} {b}' for b in judge(spec, v)]
    return values, failures, rules


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config'); ap.add_argument('--board'); ap.add_argument('--metrics'); ap.add_argument('--json')
    a = ap.parse_args()
    proj = Project(a.config)
    values, failures, rules = evaluate(proj, a.board, a.metrics)
    out = {'values': values, 'failures': failures}
    if a.json:
        write_json(a.json, out)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    sys.exit(1 if failures else 0)
