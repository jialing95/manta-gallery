#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Build the legacy Aqaba LSB C10 gallery case from local D-Claw FORT output.

Usage:
  ./scripts/build_site.sh <case-root-or-output-dir> [options]

This is a compatibility wrapper around:

  ./scripts/build_case.sh aqaba_case_001 <case-root-or-output-dir> \
    --title "Aqaba LSB C10" \
    --label "LSB C10"

For new cases, call scripts/build_case.sh directly.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if (($# < 1)); then
  usage
  exit 2
fi

exec "$REPO_ROOT/scripts/build_case.sh" aqaba_case_001 "$@" \
  --title "Aqaba LSB C10" \
  --label "LSB C10" \
  --card-description "Interactive 3D view of landslide tsunami (case: LSB C10) in the Gulf of Aqaba." \
  --overview 'Aqaba LSB C10 is an interactive 3D D-Claw landslide-tsunami case for the Gulf of Aqaba. `LSB` denotes Landslide B, and `C10` denotes a contractive landslide mixture with permeability coefficient $10^{-10}$. The viewer combines a static high-resolution topo-bathymetric surface with time-dependent water height and landslide fields for browser-side exploration.' \
  "$@"
