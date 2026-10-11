"""Place footprints from layout/placement.toml: connectors, mounting holes, RF and power parts that
the design fixes on purpose. Placed parts can be locked so routers and later edits leave them alone.

  origin = "outline"          # coordinates from the outline's top-left corner ("absolute": KiCad's)

  [[part]]
  ref = "J1"
  at = [0.0, 10.0]            # mm, footprint origin
  rot = 90                    # degrees
  side = "F"                  # F or B
  lock = true
  ref_offset = [0.0, -4.0]    # optional: reference text position from the footprint origin (board axes, mm)
  why = "USB-C on the left edge, flush with the outline"

usage: python3 pcbkit/place.py [--config pcb.toml] [--placement layout/placement.toml] [--dry-run]
Prints the parts it moved; run the gate afterwards (courtyard overlaps show up as DRC errors).
"""
import argparse, json, sys, tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import kicad_compat as kc  # noqa: E402

k = kc.pcbnew


def main():
    ap = argparse.ArgumentParser(description='Place footprints from a placement file')
    ap.add_argument('--config'); ap.add_argument('--placement', default='layout/placement.toml'); ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    p = common.Project(a.config)
    cfg = tomllib.loads((p.root / a.placement).read_text(encoding='utf-8'))
    pro_text = p.pro.read_text() if p.pro and p.pro.exists() else None
    b = kc.load_board(p.pcb)
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    ox = oy = 0
    if cfg.get('origin', 'outline') == 'outline':
        ox, oy = kc.outline_origin(b)
    moved, missing = [], []
    for part in cfg.get('part', []):
        f = fps.get(part['ref'])
        if f is None:
            missing.append(part['ref']); continue
        if not part.get('why'):
            sys.exit(f"{part['ref']}: every placement needs a why")
        want_back = part.get('side', 'F') == 'B'
        if f.IsFlipped() != want_back:
            f.Flip(f.GetPosition(), k.FLIP_DIRECTION_TOP_BOTTOM)
        f.SetOrientationDegrees(part.get('rot', 0))
        f.SetPosition(k.VECTOR2I(ox + k.FromMM(part['at'][0]), oy + k.FromMM(part['at'][1])))
        f.SetLocked(bool(part.get('lock', False)))
        if 'ref_offset' in part:          # silkscreen cleanup: move the reference text off pads and other text
            ref = f.Reference()
            ref.SetPosition(k.VECTOR2I(f.GetPosition().x + k.FromMM(part['ref_offset'][0]), f.GetPosition().y + k.FromMM(part['ref_offset'][1])))
            ref.SetTextAngleDegrees(part.get('ref_rot', 0))
        moved.append(part['ref'])
    if not a.dry_run:
        k.SaveBoard(str(p.pcb), b)
        if pro_text is not None:
            p.pro.write_text(pro_text)
    print(json.dumps({'placed': moved, 'missing': missing}, ensure_ascii=False))
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
