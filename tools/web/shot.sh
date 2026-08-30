#!/usr/bin/env bash
# Render one URL of the local static site to a PNG with headless Edge.
#   tools/web/shot.sh <url> <out.png> [width] [height]
#
# Note: headless Edge on Windows will not lay out below ~492 CSS px wide — it
# renders at 492 and crops the capture. Phone-width review has to be done in a
# browser that emulates the viewport properly; this tool covers 500 px and up.
set -euo pipefail
EDGE="${EDGE_BIN:-/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe}"
OUT_WIN=$(cygpath -w "$2" 2>/dev/null || echo "$2")
"$EDGE" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --window-size="${3:-1440},${4:-2200}" --virtual-time-budget=4000 \
  --screenshot="$OUT_WIN" "$1" >/dev/null 2>&1
