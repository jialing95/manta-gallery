#!/usr/bin/env bash
set -euo pipefail

mkdir -p docs/assets/data/demo

rsync -av --delete \
  data/demo/aqaba_case_001/ \
  docs/assets/data/demo/aqaba_case_001/
