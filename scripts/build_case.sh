#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Build one MANTA Gallery case from local D-Claw FORT output.

Usage:
  ./scripts/build_case.sh <case-id> <case-root-or-output-dir> [options]

Example:
  ./scripts/build_case.sh aqaba_lsa_c10 /path/to/dclaw-case \
    --title "Aqaba LSA C10" \
    --label "LSA C10"

Options:
  --title <text>            Case title shown in the page and viewer.
  --label <text>            Short label used in gallery text. Default: title.
  --card-description <text> Gallery card description.
  --overview <text>         Markdown overview shown above the viewer.
  --manta-src <dir>         MANTA/preprocessor source tree.
                            Default: $MANTA_SRC or ~/Desktop/preprocessor
  --python <executable>     Python environment with numpy, scipy, and pyvista.
                            Default: $MANTA_PYTHON or <manta-src>/.venv/bin/python
  --frame-index <n>         Native default frame passed to the exporter.
  --frame-step <n>          Native frame stride for exported browser frames.
  --push                    Commit this case's canonical assets/pages and push origin/main.
  --commit-message <text>   Commit message used with --push.
  -h, --help                Show this help.

The input may be either a case root containing _output/fort.* or the output
directory that directly contains fort.q####, fort.t####, and fort.b####.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

CASE_ID=""
INPUT_DIR=""
TITLE=""
LABEL=""
CARD_DESCRIPTION=""
OVERVIEW=""
MANTA_SRC="${MANTA_SRC:-$HOME/Desktop/preprocessor}"
PYTHON_BIN="${MANTA_PYTHON:-}"
FRAME_INDEX=""
FRAME_STEP=""
PUSH=false
COMMIT_MESSAGE=""
POSITIONALS=()

while (($#)); do
  case "$1" in
    --title)
      (($# >= 2)) || fail "--title requires text"
      TITLE="$2"
      shift 2
      ;;
    --label)
      (($# >= 2)) || fail "--label requires text"
      LABEL="$2"
      shift 2
      ;;
    --card-description)
      (($# >= 2)) || fail "--card-description requires text"
      CARD_DESCRIPTION="$2"
      shift 2
      ;;
    --overview)
      (($# >= 2)) || fail "--overview requires text"
      OVERVIEW="$2"
      shift 2
      ;;
    --manta-src)
      (($# >= 2)) || fail "--manta-src requires a directory"
      MANTA_SRC="$2"
      shift 2
      ;;
    --python)
      (($# >= 2)) || fail "--python requires an executable"
      PYTHON_BIN="$2"
      shift 2
      ;;
    --frame-index)
      (($# >= 2)) || fail "--frame-index requires an integer"
      FRAME_INDEX="$2"
      shift 2
      ;;
    --frame-step)
      (($# >= 2)) || fail "--frame-step requires an integer"
      FRAME_STEP="$2"
      shift 2
      ;;
    --push)
      PUSH=true
      shift
      ;;
    --commit-message)
      (($# >= 2)) || fail "--commit-message requires text"
      COMMIT_MESSAGE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      fail "unknown option: $1"
      ;;
    *)
      POSITIONALS+=("$1")
      shift
      ;;
  esac
done

[[ "${#POSITIONALS[@]}" -eq 2 ]] || {
  usage
  exit 2
}

CASE_ID="${POSITIONALS[0]}"
INPUT_DIR="${POSITIONALS[1]}"

[[ "$CASE_ID" =~ ^[a-z0-9_]+$ ]] || fail "case-id must contain only lowercase letters, numbers, and underscores"
[[ -n "$TITLE" ]] || TITLE="$CASE_ID"
[[ -n "$LABEL" ]] || LABEL="$TITLE"
[[ -n "$CARD_DESCRIPTION" ]] || CARD_DESCRIPTION="Interactive 3D view of landslide tsunami (case: $LABEL) in the Gulf of Aqaba."
[[ -n "$OVERVIEW" ]] || OVERVIEW="$TITLE is an interactive 3D D-Claw landslide-tsunami case for the Gulf of Aqaba. The viewer combines a static high-resolution topo-bathymetric surface with time-dependent water height and landslide fields for browser-side exploration."
[[ -n "$COMMIT_MESSAGE" ]] || COMMIT_MESSAGE="Refresh $TITLE gallery assets"

[[ -d "$INPUT_DIR" ]] || fail "D-Claw case directory does not exist: $INPUT_DIR"
INPUT_DIR="$(cd "$INPUT_DIR" && pwd -P)"

FORT_DIR=""
for candidate in "$INPUT_DIR" "$INPUT_DIR/_output"; do
  if [[ -d "$candidate" ]] && compgen -G "$candidate/fort.q[0-9][0-9][0-9][0-9]" >/dev/null; then
    FORT_DIR="$candidate"
    break
  fi
done
[[ -n "$FORT_DIR" ]] || fail "no fort.q#### files found under $INPUT_DIR or $INPUT_DIR/_output"

for kind in q t b; do
  compgen -G "$FORT_DIR/fort.$kind[0-9][0-9][0-9][0-9]" >/dev/null \
    || fail "no fort.$kind#### files found in $FORT_DIR"
done

[[ -d "$MANTA_SRC" ]] || fail "MANTA source tree does not exist: $MANTA_SRC"
MANTA_SRC="$(cd "$MANTA_SRC" && pwd -P)"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$MANTA_SRC/.venv/bin/python" ]]; then
    PYTHON_BIN="$MANTA_SRC/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || true)"
  fi
fi
[[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || fail "no usable Python executable found; pass --python"

if [[ -n "$FRAME_INDEX" && ! "$FRAME_INDEX" =~ ^[0-9]+$ ]]; then
  fail "--frame-index must be a non-negative integer"
fi
if [[ -n "$FRAME_STEP" && ! "$FRAME_STEP" =~ ^[1-9][0-9]*$ ]]; then
  fail "--frame-step must be a positive integer"
fi

if "$PUSH"; then
  [[ "$(git branch --show-current)" == "main" ]] || fail "--push is only supported from the main branch"
  git diff --cached --quiet || fail "the Git index already contains staged changes; commit or unstage them before --push"
  UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
  [[ -n "$UPSTREAM" ]] || fail "main has no upstream branch"
  [[ "$(git rev-list --count "$UPSTREAM"..HEAD)" == "0" ]] \
    || fail "main already contains unpushed commits; push or resolve them before --push"
fi

node_is_compatible() {
  "$1" -e '
    const [major, minor] = process.versions.node.split(".").map(Number);
    process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1);
  ' >/dev/null 2>&1
}

NODE_BIN_DIR="${NODE_BIN_DIR:-}"
if [[ -n "$NODE_BIN_DIR" ]]; then
  node_is_compatible "$NODE_BIN_DIR/node" || fail "NODE_BIN_DIR does not contain a Vite-compatible Node.js"
elif command -v node >/dev/null && node_is_compatible "$(command -v node)"; then
  NODE_BIN_DIR="$(dirname "$(command -v node)")"
elif [[ -d "$HOME/.nvm/versions/node" ]]; then
  while IFS= read -r candidate; do
    if node_is_compatible "$candidate/node"; then
      NODE_BIN_DIR="$candidate"
      break
    fi
  done < <(find "$HOME/.nvm/versions/node" -mindepth 2 -maxdepth 2 -type d -name bin | sort -Vr)
fi
[[ -n "$NODE_BIN_DIR" ]] || fail "Node.js ^20.19 or >=22.12 is required by Vite; install Node 22 or set NODE_BIN_DIR"
export PATH="$NODE_BIN_DIR:$PATH"

command -v npm >/dev/null || fail "npm was not found after selecting Node.js"
command -v quarto >/dev/null || fail "quarto was not found"
command -v rsync >/dev/null || fail "rsync was not found"

OUTDIR="data/demo/$CASE_ID"
EXPORT_DESCRIPTION="$TITLE time-series D-Claw export with water height and landslide material fields."

printf '[BUILD] Case id:    %s\n' "$CASE_ID"
printf '[BUILD] Title:      %s\n' "$TITLE"
printf '[BUILD] FORT input: %s\n' "$FORT_DIR"
printf '[BUILD] Output:     %s\n' "$OUTDIR"
printf '[BUILD] MANTA src:  %s\n' "$MANTA_SRC"
printf '[BUILD] Python:     %s\n' "$PYTHON_BIN"
printf '[BUILD] Node:       %s\n' "$(node --version)"

PYTHONPATH="$MANTA_SRC${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" -c 'import numpy, scipy, pyvista; from visualization.dclaw_layers import DClawFortCacheCube' \
  || fail "Python export dependencies are missing; use the preprocessor virtual environment with --python"

EXPORT_ARGS=(
  --case-dir "$INPUT_DIR"
  --manta-src "$MANTA_SRC"
  --outdir "$OUTDIR"
  --title "$TITLE"
  --description "$EXPORT_DESCRIPTION"
)
AMR_ARGS=(
  --case-dir "$INPUT_DIR"
  --manta-src "$MANTA_SRC"
  --outdir "$OUTDIR"
)
if [[ -n "$FRAME_INDEX" ]]; then
  EXPORT_ARGS+=(--frame-index "$FRAME_INDEX")
  AMR_ARGS+=(--frame-index "$FRAME_INDEX")
fi
if [[ -n "$FRAME_STEP" ]]; then
  EXPORT_ARGS+=(--frame-step "$FRAME_STEP")
  AMR_ARGS+=(--frame-step "$FRAME_STEP")
fi

"$PYTHON_BIN" scripts/export_aqaba_case_001.py "${EXPORT_ARGS[@]}"
"$PYTHON_BIN" scripts/export_aqaba_case_001_amr.py "${AMR_ARGS[@]}"

DEFAULT_FRAME_INDEX="$("$PYTHON_BIN" -c 'import json, sys; print(int(json.load(open(sys.argv[1], encoding="utf-8"))["time"]["default_index"]))' "$OUTDIR/case.json")"

"$PYTHON_BIN" scripts/update_case_pages.py \
  --case-id "$CASE_ID" \
  --title "$TITLE" \
  --label "$LABEL" \
  --card-description "$CARD_DESCRIPTION" \
  --overview "$OVERVIEW" \
  --default-frame-index "$DEFAULT_FRAME_INDEX"

npm ci
npm run build:viewer
./scripts/sync_demo_assets.sh

CACHE_ROOT="${MANTA_GALLERY_CACHE_DIR:-/tmp/manta-gallery-$UID}"
mkdir -p "$CACHE_ROOT/xdg" "$CACHE_ROOT/quarto" "$CACHE_ROOT/deno"
XDG_CACHE_HOME="$CACHE_ROOT/xdg" \
  QUARTO_CACHE_DIR="$CACHE_ROOT/quarto" \
  DENO_DIR="$CACHE_ROOT/deno" \
  quarto render docs

printf '\n[OK] Local site rendered: %s\n' "$REPO_ROOT/docs/_site/index.html"

if "$PUSH"; then
  git add -- "$OUTDIR" docs/cases/cases.json docs/gallery.qmd "docs/cases/$CASE_ID.qmd"
  if git diff --cached --quiet -- "$OUTDIR" docs/cases/cases.json docs/gallery.qmd "docs/cases/$CASE_ID.qmd"; then
    printf '[PUBLISH] Case assets/pages did not change; nothing to commit or push.\n'
  else
    git commit -m "$COMMIT_MESSAGE"
    git push origin main
    printf '[OK] GitHub Pages deployment started: https://github.com/jialing95/manta-gallery/actions\n'
  fi
else
  printf '[NEXT] Preview through a local HTTP server:\n'
  printf '       ./scripts/preview_site.sh\n'
  printf '[NEXT] Publish after reviewing the local site:\n'
  printf '       ./scripts/build_case.sh %q %q --title %q --label %q --push\n' "$CASE_ID" "$INPUT_DIR" "$TITLE" "$LABEL"
fi
