#!/usr/bin/env bash
# Install kicad-happy (MIT, https://github.com/aklofas/kicad-happy) at a pinned release into
# ~/.cache/pcb-pipeline/kicad-happy-<tag>. pcbkit/extras.py uses only its analyzer scripts
# (schematic, PCB, EMC; standard-library Python); its Claude/Codex skills are NOT installed, because
# they overlap the pcb-* skills. Prints the directory to use.
#
# usage: setup_kicad_happy.sh [tag]   default tag below; newer releases go through a trial branch first
set -euo pipefail
TAG="${1:-v2.3.1}"
COMMIT_v2_3_1=06840467ad0f5d76af45f64449b1f5ecb10f052f
DEST="${PCB_PIPELINE_CACHE:-$HOME/.cache/pcb-pipeline}/kicad-happy-$TAG"
if [ ! -d "$DEST/.git" ]; then
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$TAG" https://github.com/aklofas/kicad-happy "$DEST"
fi
if [ "$TAG" = v2.3.1 ]; then
  [ "$(git -C "$DEST" rev-parse HEAD)" = "$COMMIT_v2_3_1" ] || { echo "$DEST is not at $COMMIT_v2_3_1"; exit 1; }
fi
for s in kicad/scripts/analyze_schematic.py kicad/scripts/analyze_pcb.py emc/scripts/analyze_emc.py; do
  [ -f "$DEST/skills/$s" ] || { echo "missing $DEST/skills/$s"; exit 1; }
done
echo "$DEST"
