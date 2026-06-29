#!/bin/bash
# Usage: source venv.sh  (from any cwd)
_CAM_ACQ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${_CAM_ACQ_ROOT}/.venv/bin/activate"
export LD_LIBRARY_PATH="${_CAM_ACQ_ROOT}/sdk/Galaxy_camera/c/lib/x86_64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
