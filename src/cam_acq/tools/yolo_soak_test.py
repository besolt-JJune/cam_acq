#!/usr/bin/env python3
"""YOLO live soak: continuous recording without detection trigger.

Covers field checks that need long YOLO+NVENC runs with real segments:
  - 3.1 / 6.4 — 2ch live stability + recording
  - Phase 6 T5 — split interval (duration > RECORDING_SPLIT_INTERVAL_SEC)
  - Phase 6 T7 — FIFO_DELETE (lower STORAGE_FULL_PERCENTAGE in .env to force cleanup)

T8 FIFO_REJECT is not implemented yet (storage.py only supports FIFO_DELETE).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# gi (via deepstream_yolo_live) must init before numpy — do not import config first.
from cam_acq.tools.deepstream_yolo_live import manual_record_stop_at_sec, run_live
from cam_acq.config import setup_galaxy_lib_path


def run_yolo_soak(
    *,
    duration_sec: float,
    env_file: Path | None,
    output_json: Path | None,
    record_stop_at_sec: float | None,
    no_overlay_mp4: bool,
) -> int:
    """Run cam-acq-yolo-live with manual recording from t=0 (no person trigger)."""
    stop_at = manual_record_stop_at_sec(
        duration_sec=duration_sec,
        explicit=record_stop_at_sec,
    )
    if duration_sec < stop_at + 1.0:
        print("duration too short for record window + encode margin", file=sys.stderr)
        return 1
    record_path = None if no_overlay_mp4 else Path("samples/deepstream_yolo_soak_overlay_2ch.mp4")
    return run_live(
        duration_sec=duration_sec,
        env_file=env_file,
        record_path=record_path,
        output_json=output_json,
        event_recording=False,
        record_from_start=True,
        record_stop_at_sec=stop_at,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="YOLO live soak with NVENC from start (no detection trigger)",
    )
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument(
        "--duration",
        type=float,
        default=1800.0,
        help="total run seconds (default 30 min)",
    )
    parser.add_argument(
        "--record-stop-at",
        type=float,
        default=None,
        metavar="SEC",
        help="manual_stop N sec after start (default: duration-5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("healthcheck/yolo_soak.json"),
        help="JSON report path",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="skip overlay MP4 (fakesink); NVENC event files still written",
    )
    args = parser.parse_args()
    setup_galaxy_lib_path()
    return run_yolo_soak(
        duration_sec=args.duration,
        env_file=args.env_file,
        output_json=args.output,
        record_stop_at_sec=args.record_stop_at,
        no_overlay_mp4=args.no_record,
    )


if __name__ == "__main__":
    raise SystemExit(main())
