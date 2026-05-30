#!/usr/bin/env bash
set -euo pipefail

mkdir -p docs/assets/data/demo

rsync -av --delete \
  data/demo/ \
  docs/assets/data/demo/
