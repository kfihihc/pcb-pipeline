#!/usr/bin/env bash
# Link the pcb-pipeline skills into the agent skill directories (Claude Code: ~/.claude/skills, Codex: ~/.codex/skills).
# Symlinks keep the skills in this repository, so a git pull updates them; --uninstall removes only our links.
#
# usage: ./install.sh [--check | --uninstall]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGETS=("$HOME/.claude/skills" "$HOME/.codex/skills")
mode="${1:-install}"

for target in "${TARGETS[@]}"; do
  [ -d "$target" ] || { echo "skip $target (not present)"; continue; }
  for skill in "$HERE"/skills/*/; do
    name="$(basename "$skill")"
    link="$target/$name"
    case "$mode" in
      --uninstall)
        if [ -L "$link" ] && [ "$(readlink -f "$link")" = "$(readlink -f "$skill")" ]; then rm "$link"; echo "removed $link"; fi ;;
      --check)
        if [ -L "$link" ]; then echo "ok      $link -> $(readlink "$link")"; elif [ -e "$link" ]; then echo "CONFLICT $link exists and is not our link"; else echo "missing $link"; fi ;;
      *)
        if [ -e "$link" ] && [ ! -L "$link" ]; then echo "CONFLICT $link exists and is not a link; left alone"; continue; fi
        ln -sfn "${skill%/}" "$link"; echo "linked  $link" ;;
    esac
  done
done

if [ "$mode" = "--check" ]; then
  export PATH="$HOME/.local/bin:$PATH"
  for c in kicad-cli pdftotext pdftoppm pdfinfo uv git; do printf '%-10s %s\n' "$c" "$(command -v $c || echo MISSING)"; done
  kicad-cli version 2>/dev/null | sed 's/^/kicad      /'
  python3 -c "import ctypes; ctypes.CDLL('libngspice.so.0'); print('libngspice ok')" 2>/dev/null || echo "libngspice MISSING (apt: libngspice0)"
  ls "$HOME/.cache/pcb-pipeline/jlcpcb-tools/"*.db 2>/dev/null | sed 's/^/parts db   /' || echo "parts db   none (jlc_parts.py fetch)"
  ls -d "$HOME/.cache/pcb-pipeline/KiCadRoutingTools-"* 2>/dev/null | sed 's/^/router     /' || echo "router     none (setup_krt.sh)"
  ls -d "$HOME/.cache/pcb-pipeline/kicad-happy-"* 2>/dev/null | sed 's/^/emc        /' || echo "emc        none (skills/pcb-review/scripts/setup_kicad_happy.sh)"
  echo "extras     per project: uv sync --group extras; python3 pcbkit/extras.py status"
fi
