#!/usr/bin/env bash
set -euo pipefail

mkdir -p docs/assets/data/demo

rsync -a --delete \
  data/demo/ \
  docs/assets/data/demo/

printf '[SYNC] Canonical gallery assets copied to docs/assets/data/demo\n'
