#!/bin/bash
# Production: YOLO live + monitoring dashboard + person-trigger NVENC recording.
# Dashboard bbox is browser-only (canvas); event MP4s on STORAGE_PATH have no overlay.
# Settings (cameras, debayer, storage, codec) come from .env in repo root.
#
# Usage: ./scripts/yolo_live_dashboard.sh [duration_sec]
#   duration_sec: 0 or omit → run until Ctrl+C (default)
#   Dashboard: http://127.0.0.1:${MONITORING_WEB_PORT:-8080}
#
# Timed run: ./scripts/yolo_live_dashboard.sh 3600
# Soak (no event record): ./scripts/yolo_live_dashboard.sh 3600 --no-event-recording
# Debug overlay MP4 (optional): append --record recordings/yolo_overlay_debug.mp4
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/venv.sh"
cd "${ROOT}"

DURATION="0"
if [[ "${1:-}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  DURATION="${1}"
  shift || true
fi

PORT="${MONITORING_WEB_PORT:-8080}"
if [[ -f "${ROOT}/.env" ]]; then
  # ponytail: read port only; load_settings runs inside cam-acq-yolo-live
  _p="$(grep -E '^MONITORING_WEB_PORT=' "${ROOT}/.env" | tail -1 | cut -d= -f2- | tr -d ' \"')"
  [[ -n "${_p}" ]] && PORT="${_p}"
fi

if [[ "${DURATION}" == "0" ]]; then
  DURATION_LABEL="until Ctrl+C"
else
  DURATION_LABEL="${DURATION}s"
fi

echo "Dashboard: http://127.0.0.1:${PORT}/"
echo "Duration: ${DURATION_LABEL}"
echo "Event recording: ON → STORAGE_PATH from .env (no bbox on MP4)"
echo "Dashboard bbox: browser overlay only (MJPEG stream is clean)"
echo ""

exec uv run cam-acq-yolo-live \
  --with-monitoring \
  --no-record \
  --duration "${DURATION}" \
  "$@"
