# S3 AMOLED 1.75C — KiCanvas preview

[Open the schematic and PCB in KiCanvas](https://kicanvas.org/?repo=https%3A%2F%2Fgithub.com%2Fkfihihc%2Fpcb-pipeline%2Ftree%2Fs3-kicanvas%2Fpreviews%2Fs3)

Browser preview of the KiCad reconstruction, revision **v0.2.1**: 10 schematic sheets and a four-layer PCB. Use the KiCanvas project panel to switch sheets or open the board.

The KiCad files are copied unchanged. `provenance.json` records their source commit and SHA-256 hashes. This preview does not certify fabrication readiness. Design notes are in `DESIGN-NOTES.zh-CN.md`.

For local viewing, serve this folder with `python3 -m http.server --bind 127.0.0.1 8768` and open http://127.0.0.1:8768/ . The embedded viewer is bundled with its MIT license.

## Attribution

The hardware reconstruction derives from Waveshare ESP32-S3-Touch-AMOLED-1.75C documentation under Apache-2.0. This folder keeps that attribution and license; it is not covered by the parent repository's MIT license. See `NOTICE.md`, `LICENSE`, and the third-party notices in `sources/`.
