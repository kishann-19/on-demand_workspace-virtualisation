#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements-dev.txt
docker build -t cloudlab-workspace:local runtime
# DATA_DIR overrides the container path in .env when running on the host.
DATA_DIR="$PWD/data" exec .venv/bin/uvicorn app.main:create_app --factory --env-file .env --host 127.0.0.1 --port 8000 --reload --ws-max-size 32768
