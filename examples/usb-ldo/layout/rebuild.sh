#!/usr/bin/env bash
# Rebuild the layout from its text description, in order. Valid only while every layout decision lives in
# layout/*.toml (no hand edits in the board editor); afterwards run the gate.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -f hw/usb-ldo.kicad_pcb
python3 pcbkit/board_setup.py      # outline, layers, rules, net classes (zones and keepouts once parts exist)
python3 pcbkit/sync_pcb.py         # footprints, nets and fields from the schematic
python3 pcbkit/place.py            # layout/placement.toml
python3 pcbkit/board_setup.py      # zones and keepouts
python3 pcbkit/preroute.py         # layout/preroute.toml: locked critical routes (VBUS)
python3 pcbkit/route.py            # KiCadRoutingTools on a scratch copy; adopted only if DRC is clean
