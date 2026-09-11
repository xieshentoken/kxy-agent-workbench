#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  printf '请先运行 ./setup.sh\n' >&2
  exit 1
fi
export DO_NOT_TRACK=true
export LANGFLOW_DO_NOT_TRACK=true
export LANGFLOW_CONFIG_DIR="${KXY_DATA_ROOT:-$PWD/data}/lfx"
mkdir -p "$LANGFLOW_CONFIG_DIR"
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port "${KXY_PORT:-8710}"
