#!/usr/bin/env bash
# Install KiCadRoutingTools (MIT, https://github.com/drandyhaas/KiCadRoutingTools) at a pinned release
# into ~/.cache/pcb-pipeline/KiCadRoutingTools-<tag>, with its prebuilt Rust router (no Rust toolchain)
# and a uv environment on the system Python (numpy, scipy, shapely). Prints the python to use.
#
# usage: setup_krt.sh [tag]          default tag below; newer releases go through a trial branch first
set -euo pipefail
TAG="${1:-v0.22.1}"
DEST="${PCB_PIPELINE_CACHE:-$HOME/.cache/pcb-pipeline}/KiCadRoutingTools-$TAG"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || { echo "uv not found (install it with pipx)"; exit 1; }
if [ ! -d "$DEST/.git" ]; then
  git clone --quiet --depth 1 --branch "$TAG" https://github.com/drandyhaas/KiCadRoutingTools "$DEST"
fi
cd "$DEST"
if [ ! -d .venv ]; then
  uv venv --quiet --python /usr/bin/python3 --python-preference only-system .venv
  uv pip install --quiet --python .venv/bin/python "numpy>=1.22" scipy shapely
fi
if ! ls grid_router* rust_router/*.so 2>/dev/null | grep -q .; then
  .venv/bin/python build_router.py --tag "$TAG"
fi
.venv/bin/python -c "import numpy, scipy, shapely; print('deps ok')" >/dev/null
echo "$DEST/.venv/bin/python"
