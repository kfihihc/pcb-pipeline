# Vendored third-party files

Copied verbatim and pinned; `pcbkit/extras.py` uses them. Do not edit. To upgrade, download the new
file, record the new values here, and rerun `tests/run_tests.sh`.

| File | Source | Version | Size | SHA-256 | License |
| --- | --- | --- | --- | --- | --- |
| `kicanvas.js` | https://kicanvas.org/kicanvas/kicanvas.js (built from https://github.com/theacodes/kicanvas, main at b031159) | no releases; file last modified 2026-04-28 17:38:52 GMT, downloaded 2026-10-10 | 477451 bytes | `ca910f25276c3efb9aacb3a5d6341d4d9af4736d4c875fb0440d2cc856865ab7` | MIT, see `kicanvas.LICENSE.md` (with notices for the bundled fonts and libraries) |

Notes:

- KiCanvas calls itself an alpha. It is a viewer only: what the gate checks comes from kicad-cli, never from it.
- Browsers refuse to load the board files over `file://`, so serve the folder over HTTP
  (`python3 -m http.server --directory <folder> 8000`, then open http://localhost:8000/).
- The script requests the interface font from fonts.googleapis.com; the drawings use the Newstroke
  font bundled in the script, so they render offline too.
