#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CACHE_ROOT="${MANTA_GALLERY_CACHE_DIR:-/tmp/manta-gallery-$UID}"
mkdir -p "$CACHE_ROOT/xdg" "$CACHE_ROOT/quarto" "$CACHE_ROOT/deno"

XDG_CACHE_HOME="$CACHE_ROOT/xdg" \
  QUARTO_CACHE_DIR="$CACHE_ROOT/quarto" \
  DENO_DIR="$CACHE_ROOT/deno" \
  exec quarto preview docs "$@"
