"""Load the system KiCad pcbnew module and patch the Debian KiCad 10 build. Import before using pcbnew.

- pcbnew is compiled for the system Python, so the system dist-packages directory is appended to
  sys.path; this also works from a uv virtual environment created with the system interpreter.
- Debian's KiCad 10.0.6 (Python 3.14) iterates TRACKS and DRAWINGS (`board.GetTracks()`,
  `board.GetDrawings()`, `footprint.GraphicalItems()`) through `SwigPyIterator.next()`, which its
  SWIG runtime no longer defines, so every such loop raises AttributeError. Alias it to __next__.
"""
import sys

for _path in ('/usr/lib/python3/dist-packages', '/usr/lib/kicad/lib/python3/dist-packages'):
    if _path not in sys.path:
        sys.path.append(_path)

import pcbnew  # noqa: E402

if hasattr(pcbnew, 'SwigPyIterator') and not hasattr(pcbnew.SwigPyIterator, 'next'):
    pcbnew.SwigPyIterator.next = pcbnew.SwigPyIterator.__next__


def load_board(path):
    return pcbnew.LoadBoard(str(path))


def is_via(item):
    return isinstance(item, pcbnew.PCB_VIA)


def tracks(board):
    """Track segments and arcs (no vias)."""
    return [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]


def vias(board):
    return [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]


def outline_origin(board):
    """Top-left corner of the board outline geometry (Edge.Cuts end points, ignoring line width)."""
    xs, ys = [], []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and isinstance(d, pcbnew.PCB_SHAPE):
            for pt in (d.GetStart(), d.GetEnd()):
                xs.append(pt.x); ys.append(pt.y)
    if not xs:
        return 0, 0
    return min(xs), min(ys)
