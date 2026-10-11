"""Explicit routes for critical nets (power entry, switch nodes, RF feeds, USB pairs), written as text,
placed on the board and locked, so that autorouters treat them as fixed copper and reviews see intent.

layout/preroute.toml (coordinates in mm from the outline's top-left corner, or "REF.PAD" for a pad centre):

  [[track]]
  net = "VBUS"
  layer = "F.Cu"
  width = 0.5
  points = ["J1.B9", [7.3, 7.48]]       # a polyline; consecutive points become segments
  why = "VBUS exits behind the USB-C pads, not under the shell"

  [[via]]
  net = "VBUS"
  at = [7.3, 7.48]
  size = 0.6
  drill = 0.3
  why = "to the back-side VBUS run"

Running it again first removes the copper it placed before (items carry the group "pcbkit-preroute"),
so the file stays the single description. Everything is locked unless lock = false.
usage: python3 pcbkit/preroute.py [--config pcb.toml] [--file layout/preroute.toml] [--remove]
"""
import argparse, json, sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import kicad_compat as kc  # noqa: E402

k = kc.pcbnew
GROUP = 'pcbkit-preroute'


def main():
    ap = argparse.ArgumentParser(description='Place locked critical routes from a text file')
    ap.add_argument('--config'); ap.add_argument('--file', default='layout/preroute.toml'); ap.add_argument('--remove', action='store_true')
    a = ap.parse_args()
    p = common.Project(a.config)
    pro_text = p.pro.read_text() if p.pro and p.pro.exists() else None
    b = kc.load_board(p.pcb)
    removed = 0
    for g in list(b.Groups()):
        if g.GetName() == GROUP:
            for item in list(g.GetItems()):
                b.Remove(item); removed += 1
            b.Remove(g)
    placed = {'tracks': 0, 'vias': 0}
    if not a.remove:
        cfg = tomllib.loads((p.root / a.file).read_text(encoding='utf-8'))
        ox, oy = kc.outline_origin(b)
        fps = {f.GetReference(): f for f in b.GetFootprints()}
        group = k.PCB_GROUP(b); group.SetName(GROUP); b.Add(group)

        def point(pt):
            if isinstance(pt, str):
                ref, _, num = pt.partition('.')
                pads = [q for q in fps[ref].Pads() if q.GetNumber() == num]
                if not pads:
                    raise SystemExit(f'no pad {pt}')
                return pads[0].GetPosition()
            return k.VECTOR2I(ox + k.FromMM(pt[0]), oy + k.FromMM(pt[1]))

        def net(name):
            n = b.FindNet(name)
            if n is None:
                raise SystemExit(f'net {name} is not on the board (run sync_pcb.py)')
            return n
        for t in cfg.get('track', []):
            if not t.get('why'):
                sys.exit(f"track on {t['net']}: every preroute needs a why")
            pts = [point(x) for x in t['points']]
            for s, e in zip(pts, pts[1:]):
                seg = k.PCB_TRACK(b)
                seg.SetStart(s); seg.SetEnd(e); seg.SetWidth(k.FromMM(t['width']))
                seg.SetLayer(b.GetLayerID(t['layer'])); seg.SetNet(net(t['net'])); seg.SetLocked(t.get('lock', True))
                b.Add(seg); group.AddItem(seg); placed['tracks'] += 1
        for v in cfg.get('via', []):
            if not v.get('why'):
                sys.exit(f"via on {v['net']}: every preroute needs a why")
            via = k.PCB_VIA(b)
            via.SetPosition(point(v['at'])); via.SetWidth(k.FromMM(v.get('size', 0.6))); via.SetDrill(k.FromMM(v.get('drill', 0.3)))
            via.SetNet(net(v['net'])); via.SetLocked(v.get('lock', True))
            b.Add(via); group.AddItem(via); placed['vias'] += 1
    b.BuildConnectivity()
    k.SaveBoard(str(p.pcb), b)
    if pro_text is not None:
        p.pro.write_text(pro_text)
    print(json.dumps({'removed': removed, **placed}))


if __name__ == '__main__':
    main()
