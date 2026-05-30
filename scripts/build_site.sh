#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Build the Aqaba LSB C10 gallery from local D-Claw FORT output.

Usage:
  ./scripts/build_site.sh <case-root-or-output-dir> [options]

Options:
  --manta-src <dir>       MANTA/preprocessor source tree.
                          Default: $MANTA_SRC or ~/Desktop/preprocessor
  --python <executable>   Python environment with numpy, scipy, and pyvista.
                          Default: $MANTA_PYTHON or <manta-src>/.venv/bin/python
  --push                  Commit canonical case assets and push origin/main
                          after the local build succeeds.
  --commit-message <text> Commit message used with --push.
  -h, --help              Show this help.

The input may be either a case root containing _output/fort.* or the output
directory that directly contains fort.q####, fort.t####, and fort.b####.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

INPUT_DIR=""
MANTA_SRC="${MANTA_SRC:-$HOME/Desktop/preprocessor}"
PYTHON_BIN="${MANTA_PYTHON:-}"
PUSH=false
COMMIT_MESSAGE="Refresh Aqaba LSB C10 gallery assets"

while (($#)); do
  case "$1" in
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
      [[ -z "$INPUT_DIR" ]] || fail "provide exactly one D-Claw case directory"
      INPUT_DIR="$1"
      shift
      ;;
  esac
done

[[ -n "$INPUT_DIR" ]] || {
  usage
  exit 2
}
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

printf '[BUILD] FORT input: %s\n' "$FORT_DIR"
printf '[BUILD] MANTA src:  %s\n' "$MANTA_SRC"
printf '[BUILD] Python:     %s\n' "$PYTHON_BIN"
printf '[BUILD] Node:       %s\n' "$(node --version)"

PYTHONPATH="$MANTA_SRC${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" -c 'import numpy, scipy, pyvista; from visualization.dclaw_layers import DClawFortCacheCube' \
  || fail "Python export dependencies are missing; use the preprocessor virtual environment with --python"

"$PYTHON_BIN" scripts/export_aqaba_case_001.py \
  --case-dir "$INPUT_DIR" \
  --manta-src "$MANTA_SRC"

"$PYTHON_BIN" scripts/export_aqaba_case_001_amr.py \
  --case-dir "$INPUT_DIR" \
  --manta-src "$MANTA_SRC"

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
  git add -- data/demo/aqaba_case_001
  if git diff --cached --quiet -- data/demo/aqaba_case_001; then
    printf '[PUBLISH] Canonical assets did not change; nothing to commit or push.\n'
  else
    git commit -m "$COMMIT_MESSAGE"
    git push origin main
    printf '[OK] GitHub Pages deployment started: https://github.com/jialing95/manta-gallery/actions\n'
  fi
else
  printf '[NEXT] Preview through a local HTTP server:\n'
  printf '       ./scripts/preview_site.sh\n'
  printf '[NEXT] Publish after reviewing the local site:\n'
  printf '       ./scripts/build_site.sh %q --push\n' "$INPUT_DIR"
fi
