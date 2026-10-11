#!/usr/bin/env bash
# Smoke tests for pcb-pipeline: the example project passes its gate, every gate check catches a deliberately
# broken copy, and the stage scripts run on real data. Uses scratch copies only; nothing in the repo changes.
# Needs: system KiCad 10, poppler-utils, rsync, uv (for SKiDL); optional: the extras group in examples/usb-ldo/.venv
# (uv sync --group extras) and data in ~/.cache/pcb-pipeline (parts DB, KiCadRoutingTools, refs/Minimal-KiCAD.zip,
# kicad-happy) - tests that need something missing are skipped, not failed.
#
# usage: tests/run_tests.sh [-k name]      (run only tests whose name contains "name")
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SK="$ROOT/skills"
EX="$ROOT/examples/usb-ldo"
CACHE="${PCB_PIPELINE_CACHE:-$HOME/.cache/pcb-pipeline}"
export PATH="$HOME/.local/bin:$PATH"
FILTER=""; [ "${1:-}" = "-k" ] && FILTER="${2:-}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0; skip=0; failed=()

run() {   # run NAME EXPECT(0|1) COMMAND...   EXPECT 1 means "must fail"
  local name="$1" expect="$2"; shift 2
  [[ -n "$FILTER" && "$name" != *"$FILTER"* ]] && return
  local log="$TMP/$name.log"
  ( "$@" ) >"$log" 2>&1; local rc=$?
  if { [ "$expect" = 0 ] && [ $rc = 0 ]; } || { [ "$expect" = 1 ] && [ $rc != 0 ]; }; then
    echo "PASS  $name"; pass=$((pass + 1))
  else
    echo "FAIL  $name (exit $rc, expected $([ "$expect" = 0 ] && echo 0 || echo non-zero))"; tail -5 "$log" | sed 's/^/      /'
    fail=$((fail + 1)); failed+=("$name")
  fi
}
skip() { [[ -n "$FILTER" && "$1" != *"$FILTER"* ]] && return; echo "SKIP  $1 ($2)"; skip=$((skip + 1)); }
copy_example() {   # without .venv (large); tests of the optional outputs point UV_PROJECT_ENVIRONMENT at the example's own
  rm -rf "$TMP/ex"; rsync -a --exclude .venv --exclude work --exclude reports --exclude release "$EX/" "$TMP/ex/"; echo "$TMP/ex"; }
grep_in() { grep -q "$1" "$2"; }

# ---------------------------------------------------------------- kit consistency
run kit_vendored_matches_canonical 0 diff -r -x __pycache__ -x MANIFEST.json "$SK/pcb-pipeline/kit" "$EX/pcbkit"
vendored() { local js="$SK/pcb-pipeline/kit/vendor/kicanvas.js"; grep -q "$(sha256sum "$js" | cut -c1-64)" "$SK/pcb-pipeline/kit/vendor/README.md" && \
  grep -q "$(stat -c %s "$js") bytes" "$SK/pcb-pipeline/kit/vendor/README.md"; }
run kit_vendor_files_match_readme 0 vendored

# ---------------------------------------------------------------- example project: everything passes
run example_gate_passes 0 bash -c "cd '$(copy_example)' && python3 pcbkit/gate.py"
run example_sim_passes 0 bash -c "cd '$EX' && python3 pcbkit/sim.py sim/benches.toml --out '$TMP/sim'"
run example_facts_check 0 bash -c "cd '$EX' && for f in data/parts/*/facts.toml; do python3 '$SK/pcb-datasheet/scripts/datasheet.py' check \$f >/dev/null || exit 1; done"

# ---------------------------------------------------------------- each check catches a broken copy
neg_intent() { local d; d=$(copy_example); cd "$d" && sed -i 's/pins = \["J1.A5", "R1.1"\]/pins = ["J1.A5", "R2.1"]/' design/intent.toml && python3 pcbkit/gate.py --only netlist; }
run negative_intent_wrong_pin 1 neg_intent
neg_rules() { local d; d=$(copy_example); cd "$d" && sed -i 's/(constraint clearance (min 0.3mm))/(constraint clearance (minimum 0.3mm))/' hw/usb-ldo.kicad_dru && python3 pcbkit/gate.py --only rules; }
run negative_rules_file_dropped 1 neg_rules
neg_metric() { local d; d=$(copy_example); cd "$d" && sed -i '0,/max = 3.0/s//max = 1.0/' checks/metrics.toml && python3 pcbkit/gate.py --only metrics; }
run negative_metric_threshold 1 neg_metric
neg_sim() { local d; d=$(copy_example); cd "$d" && sed -i 's/max = 30.0/max = 6.0/' sim/benches.toml && python3 pcbkit/gate.py --only sim; }
run negative_sim_xc6206_limit 1 neg_sim
neg_repro() { local d; d=$(copy_example); cd "$d" && sed -i 's/(value "5.1k")/(value "4.7k")/' design/usb-ldo.net && python3 pcbkit/gate.py --only reproduce; }
run negative_reproduce_stale_file 1 neg_repro
neg_drc() { local d; d=$(copy_example); cd "$d" && python3 - <<'EOF' && python3 pcbkit/gate.py --only drc
import sys; sys.path.insert(0, 'pcbkit')
import kicad_compat as kc
k = kc.pcbnew
pro = open('hw/usb-ldo.kicad_pro').read()
b = kc.load_board('hw/usb-ldo.kicad_pcb')
for f in b.GetFootprints():
    if f.GetReference() == 'R3':
        f.SetPosition(k.VECTOR2I(f.GetPosition().x + k.FromMM(2.4), f.GetPosition().y))   # onto D1
k.SaveBoard('hw/usb-ldo.kicad_pcb', b); open('hw/usb-ldo.kicad_pro', 'w').write(pro)
EOF
}
run negative_drc_overlap 1 neg_drc
neg_scope() { local d; d=$(copy_example); cd "$d" && cp hw/usb-ldo.kicad_pcb "$TMP/base.kicad_pcb" && python3 - <<'EOF' && python3 pcbkit/board_diff.py "$TMP/base.kicad_pcb" hw/usb-ldo.kicad_pcb --allow-refs C2 --allow-nets '+3V3'
import sys; sys.path.insert(0, 'pcbkit')
import kicad_compat as kc
k = kc.pcbnew
pro = open('hw/usb-ldo.kicad_pro').read()
b = kc.load_board('hw/usb-ldo.kicad_pcb')
for f in b.GetFootprints():
    if f.GetReference() == 'R1':
        f.SetPosition(k.VECTOR2I(f.GetPosition().x, f.GetPosition().y + k.FromMM(0.2)))
k.SaveBoard('hw/usb-ldo.kicad_pcb', b); open('hw/usb-ldo.kicad_pro', 'w').write(pro)
EOF
}
run negative_scope_out_of_change 1 neg_scope

# ---------------------------------------------------------------- generators
if [ -x "$EX/.venv/bin/python" ]; then
  gen_check() {
    mkdir -p "$TMP/gen/hw" && cd "$TMP/gen" && cat > g.py <<'EOF'
import os, subprocess, sys
for v in ('10', '9', '8'):
    os.environ.setdefault(f'KICAD{v}_SYMBOL_DIR', '/usr/share/kicad/symbols'); os.environ.setdefault(f'KICAD{v}_FOOTPRINT_DIR', '/usr/share/kicad/footprints')
from skidl import *
set_default_tool(KICAD10)
u = Part('Amplifier_Operational', 'LM324', ref='U1', tag='opa', footprint='Package_SO:SOIC-14_3.9x8.7mm_P1.27mm')
v = Part('Regulator_Linear', 'AP2112K-3.3', ref='U2', tag='ldo', footprint='Package_TO_SOT_SMD:SOT-23-5')
vcc, gnd, vin = Net('VCC'), Net('GND'), Net('VIN')
vcc += u[4], v['VOUT']; gnd += u[11], v['GND']; vin += v['VIN'], v['EN']
for i, (o, m, p) in enumerate([(1, 2, 3), (7, 6, 5), (8, 9, 10), (14, 13, 12)]):
    out = Net(f'OUT{i}'); out += u[o], u[m]
    r = Part('Device', 'R', ref=f'R{i+1}', tag=f'r{i}', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    vin += r[1]; r[2] += u[p]
r9 = Part('Device', 'R', ref='R9', tag='r9', value='0R', footprint='Resistor_SMD:R_0603_1608Metric'); r9.fields['DNP'] = 'yes'
vin += r9[1]; gnd += r9[2]
generate_netlist(file_='g.net')
subprocess.run([sys.executable, sys.argv[1], 'g.net', 'hw/g.kicad_sch', '--power-flag', 'VIN', '--power-flag', 'GND', '--normalize-input'], check=True)
EOF
    "$EX/.venv/bin/python" g.py "$SK/pcb-pipeline/kit/sch_gen.py" && kicad-cli sch erc --format json --severity-all -o erc.json hw/g.kicad_sch >/dev/null && \
      python3 -c "import json,sys; d=json.load(open('erc.json')); v=[x for s in d['sheets'] for x in s['violations']]; print(len(v), 'ERC'); sys.exit(1 if v else 0)" && \
      grep -q '(dnp yes)' hw/g.kicad_sch && [ "$(grep -c '(unit 5)' hw/g.kicad_sch)" -ge 1 ]
  }
  run sch_gen_multiunit_dnp_erc_clean 0 gen_check
else
  skip sch_gen_multiunit_dnp_erc_clean "no uv environment in examples/usb-ldo (cd there and run uv sync)"
fi

# ---------------------------------------------------------------- stage scripts on real data
if [ -f "$CACHE/refs/Minimal-KiCAD.zip" ]; then
  refd() { cd "$TMP" && python3 "$SK/pcb-refdesign/scripts/refnet.py" export "$CACHE/refs/Minimal-KiCAD.zip" --out ref.json && \
    python3 "$SK/pcb-refdesign/scripts/refnet.py" around ref.json U3 | grep -q 'XIN' && \
    python3 "$SK/pcb-refdesign/scripts/refnet.py" compare ref.json ref.json --anchor U3=U3 --json cmp.json && \
    python3 -c "import json,sys; d=json.load(open('cmp.json')); bad=[p for p in d['pins'] if p['status'] not in ('same','same supply class')]; sys.exit(1 if bad else 0)"; }
  run refdesign_rp2040_export_around_compare 0 refd
else
  skip refdesign_rp2040_export_around_compare "no $CACHE/refs/Minimal-KiCAD.zip"
fi
if ls "$CACHE/jlcpcb-tools/"*.db >/dev/null 2>&1; then
  parts() { python3 "$SK/pcb-parts/scripts/jlc_parts.py" show C14289 | grep -q 'HT7533-1' && \
    python3 "$SK/pcb-parts/scripts/jlc_parts.py" search 5.1kΩ --package 0603 --type basic --limit 3 | grep -q C23186; }
  run parts_db_show_and_search 0 parts
else
  skip parts_db_show_and_search "no parts database (jlc_parts.py fetch)"
fi
newp() { python3 "$SK/pcb-pipeline/scripts/new_project.py" "$TMP/np" --name np --title "np" --size 20x15 && cd "$TMP/np" && \
  python3 pcbkit/board_setup.py && python3 pcbkit/gate.py --only drc,metrics,sim; }
run new_project_board_setup_gate 0 newp
rel() {   # panel undecided, no extras installed: the package still builds, with the prompt and the skip notes
  local d; d=$(copy_example); cd "$d" && sed -i 's/^panel = "self"/panel = "ask"/' pcb.toml && \
  UV_PROJECT_ENVIRONMENT="$TMP/none" python3 pcbkit/release.py --no-gate --allow-dirty && R=release/usb-ldo-0.1.0 && \
  grep -q 'REVIEW ONLY' $R/README.txt && grep -q 'PANEL NOT DECIDED' $R/README.txt && grep -q 'ibom skipped' $R/README.txt && \
  [ ! -e $R/fab/panel ] && [ -f $R/review/kicanvas/index.html ] && \
  [ "$(wc -l < $R/assembly/jlc-cpl.csv)" = 10 ] && (cd $R && sha256sum -c SHA256SUMS >/dev/null); }
run release_package_review_only 0 rel
neg_rel_panel() { local d; d=$(copy_example); cd "$d" && UV_PROJECT_ENVIRONMENT="$TMP/none" python3 pcbkit/release.py --no-gate --allow-dirty; \
  local rc=$?; [ ! -e release/usb-ldo-0.1.0 ] || { echo "half-built package left behind"; return 0; }; return $rc; }
run negative_release_self_panel_without_kikit 1 neg_rel_panel

# ---------------------------------------------------------------- optional outputs (extras.py; advisory, not in the gate)
kc_page() { local d; d=$(copy_example); cd "$d" && python3 pcbkit/extras.py kicanvas && K=reports/extras/kicanvas && \
  [ "$(grep -c '<kicanvas-source' $K/index.html)" = 2 ] && cmp -s pcbkit/vendor/kicanvas.js $K/kicanvas.js && \
  [ -f $K/usb-ldo.kicad_sch ] && [ -f $K/usb-ldo.kicad_pcb ] && [ -f $K/usb-ldo.kicad_pro ]; }
run extras_kicanvas_page 0 kc_page
if [ -x "$EX/.venv/bin/python" ] && "$EX/.venv/bin/python" -c "import importlib.util as u, sys; sys.exit(not all(u.find_spec(m) for m in ('kikit', 'pcbdraw', 'InteractiveHtmlBom')))"; then
  xp() { UV_PROJECT_ENVIRONMENT="$EX/.venv" python3 pcbkit/extras.py "$@"; }
  ibom_page() { local d; d=$(copy_example); cd "$d" && xp ibom && grep -q 'Interactive BOM' reports/extras/ibom.html && grep -q LZString reports/extras/ibom.html; }
  run extras_ibom 0 ibom_page
  pcbdraw_svgs() { local d; d=$(copy_example); cd "$d" && xp pcbdraw && \
    python3 -c "import sys, xml.dom.minidom as m; [m.parse(f) for f in sys.argv[1:]]" reports/extras/pcbdraw-top.svg reports/extras/pcbdraw-bottom.svg; }
  run extras_pcbdraw_svg 0 pcbdraw_svgs
  panel_ok() { local d; d=$(copy_example); cd "$d" && xp panel > p.json && grep -q '"pieces": 1' p.json && grep -q '"violations": 0' p.json && \
    [ -f reports/extras/panel/top.png ]; }
  run extras_panel_one_piece_drc_clean 0 panel_ok
  neg_panel() { local d; d=$(copy_example); cd "$d" && sed -i 's/^vcount = 2 /vcount = 0 /' layout/panel.toml && xp panel; }
  run negative_panel_without_tabs 1 neg_panel
  rel_panel() { local d; d=$(copy_example); cd "$d" && UV_PROJECT_ENVIRONMENT="$EX/.venv" python3 pcbkit/release.py --no-gate --allow-dirty && \
    R=release/usb-ldo-0.1.0 && [ "$(wc -l < $R/fab/panel/jlc-cpl.csv)" = 19 ] && [ -f $R/fab/panel/gerbers.zip ] && [ -f $R/assembly/ibom.html ] && \
    grep -q 'self-panelized' $R/README.txt && (cd $R && sha256sum -c SHA256SUMS >/dev/null); }
  run release_self_panel_ibom_kicanvas 0 rel_panel
  rev_packet() { local d; d=$(copy_example); cd "$d" && UV_PROJECT_ENVIRONMENT="$EX/.venv" python3 pcbkit/review.py --no-gate && P=reports/review/packet.md && \
    grep -q '## 拼板（KiKit' $P && grep -q 'kicanvas/' $P && grep -q 'ibom.html' $P && grep -q 'pcbdraw-top.svg' $P && [ -f reports/review/panel/top.png ]; }
  run review_packet_optional_outputs 0 rev_packet
else
  skip extras_ibom_pcbdraw_panel "no extras in examples/usb-ldo/.venv (cd there and run uv sync --group extras)"
fi
if [ -f "${KICAD_HAPPY_DIR:-$CACHE/kicad-happy-v2.3.1}/skills/emc/scripts/analyze_emc.py" ]; then
  emc_scan() { local d; d=$(copy_example); cd "$d" && python3 pcbkit/extras.py emc && grep -q 'IO-001' reports/extras/emc.md && \
    python3 -c "import json; d=json.load(open('reports/extras/emc.json')); assert d['analyzer_type'] == 'emc'"; }
  run extras_emc_kicad_happy 0 emc_scan
else
  skip extras_emc_kicad_happy "no kicad-happy (skills/pcb-review/scripts/setup_kicad_happy.sh)"
fi

# ---------------------------------------------------------------- documentation diagrams
if [ -f "$CACHE/mermaid/mermaid.min.js" ] && { [ -n "${CHROME:-}" ] || ls "$HOME"/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell >/dev/null 2>&1; }; then
  run diagrams_render 0 python3 "$ROOT/tools/diagrams.py" --check "$ROOT/README.md" "$ROOT/README.zh-CN.md" "$ROOT/PIPELINE.zh-CN.md" "$ROOT/docs/SKILLS.zh-CN.md" "$SK"/*/SKILL.md
else
  skip diagrams_render "no mermaid.min.js in $CACHE/mermaid or no headless Chromium"
fi

echo
echo "$pass passed, $fail failed, $skip skipped"
[ $fail = 0 ] || { printf '  %s\n' "${failed[@]}"; exit 1; }
