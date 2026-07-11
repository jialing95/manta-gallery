#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Build the default Aqaba LSA C10 angm25 gallery case from local D-Claw FORT output.

Usage:
  ./scripts/build_site.sh <case-root-or-output-dir> [options]

This is a compatibility wrapper around:

  ./scripts/build_case.sh aqaba_lsa_c10_angm25 <case-root-or-output-dir> \
    --title "Aqaba LSA C10 angm25" \
    --label "LSA C10 angm25" \
    --frame-index 20 \
    --frame-step 2

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

INPUT_DIR="$1"
shift

exec "$REPO_ROOT/scripts/build_case.sh" aqaba_lsa_c10_angm25 "$INPUT_DIR" \
  --title "Aqaba LSA C10 angm25" \
  --label "LSA C10 angm25" \
  --card-description "Interactive 3D view of landslide tsunami case AQA_017_K1_C10_angm25_mixed in the Gulf of Aqaba." \
  --overview 'Aqaba LSA C10 angm25 is an interactive 3D D-Claw landslide-tsunami case for the Gulf of Aqaba, exported from `AQA_017_K1_C10_angm25_mixed`. The viewer combines a static high-resolution topo-bathymetric surface with time-dependent water height and landslide fields for browser-side exploration. This web demo uses every second native output frame to keep the GitHub Pages payload compact while preserving the animation.' \
  --frame-index 20 \
  --frame-step 2 \
  "$@"
