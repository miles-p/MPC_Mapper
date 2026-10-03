#!/usr/bin/env bash
# Create the venv on first run, then launch MPC Mapper.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python -m mpc_mapper "$@"
