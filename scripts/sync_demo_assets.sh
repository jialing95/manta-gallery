#!/usr/bin/env bash
set -euo pipefail

mkdir -p docs/assets/data

rsync -a --delete \
  data/ \
  docs/assets/data/

printf '[SYNC] Canonical gallery assets copied to docs/assets/data\n'
