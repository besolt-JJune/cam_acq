#!/bin/bash
# Wrapper for systemd ExecStart: Galaxy lib path + venv CLI.
set -euo pipefail

ROOT="${CAM_ACQ_ROOT:?set CAM_ACQ_ROOT in unit or /etc/cam-acq/cam-acq.env}"
CLI="${1:?usage: cam-acq-run.sh <cli-name> [args...]}"
shift

LIB="${ROOT}/sdk/Galaxy_camera/c/lib/x86_64"
export LD_LIBRARY_PATH="${LIB}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

BIN="${ROOT}/.venv/bin/${CLI}"
if [[ ! -x "${BIN}" ]]; then
  echo "missing ${BIN} — run: cd ${ROOT} && uv sync" >&2
  exit 127
fi

cd "${ROOT}"
exec "${BIN}" "$@"
