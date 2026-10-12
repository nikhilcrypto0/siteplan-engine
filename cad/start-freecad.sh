#!/bin/sh
# Start FreeCAD with the siteplan live link (cad/siteplan_live.FCMacro) running.
#
# FreeCAD is given a clean environment (HOME, a plain PATH and the link's own settings) because
# the macOS FreeCAD launcher prints its whole environment on start: run from a shell that holds
# API keys, they would land in FreeCAD's log. The log goes to out/cad/freecad.log.
#
#   sh cad/start-freecad.sh            (FreeCAD from /Applications)
#   FREECAD_APP=/path/FreeCAD.app sh cad/start-freecad.sh
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
APP=${FREECAD_APP:-/Applications/FreeCAD.app}
ROOT=${SITEPLAN_CAD_ROOT:-$HERE/out/cad}
PORT=${SITEPLAN_CAD_PORT:-9877}
mkdir -p "$ROOT"
exec env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=en_US.UTF-8 \
  SITEPLAN_CAD_ROOT="$ROOT" SITEPLAN_CAD_PORT="$PORT" \
  "$APP/Contents/MacOS/FreeCAD" "$HERE/cad/siteplan_live.FCMacro" > "$ROOT/freecad.log" 2>&1
