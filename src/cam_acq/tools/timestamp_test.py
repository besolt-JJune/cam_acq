#!/usr/bin/env python3
"""Probe Galaxy camera timestamp features and optional TimestampReset."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from cam_acq.camera.timestamp import (
    TimestampCameraReport,
    probe_timestamp_readonly,
    reset_camera_timestamp,
)
from cam_acq.config import ensure_dir, load_settings, setup_galaxy_lib_path
from cam_acq.logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    """CLI: 0=all ok, 1=open/reset fail, 2=config error."""
    parser = argparse.ArgumentParser(description="Camera timestamp feature test via gxipy")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Send TimestampReset and record latch before/after (default: read-only)",
    )
    parser.add_argument("--output", type=Path, default=None, help="JSON output path")
    parser.add_argument("--log", type=Path, default=None, help="LOG_PATH override")
    args = parser.parse_args(argv)

    try:
        setup_galaxy_lib_path()
        settings = load_settings()
    except Exception as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    logger = setup_logging(args.log or settings.log_path)
    logger.info("timestamp_test start reset=%s cameras=%s", args.reset, settings.num_cameras)

    reports: list[TimestampCameraReport] = []
    for ep in settings.cameras:
        if args.reset:
            reports.append(reset_camera_timestamp(ep))
        else:
            reports.append(probe_timestamp_readonly(ep))

    any_fail = False
    cameras_json = []
    for r in reports:
        if r.open_error or r.reset_error:
            any_fail = True
        cameras_json.append(asdict(r))

    reset_supported = all(
        r.implemented.get("TimestampReset") for r in reports if not r.open_error
    )

    doc = {
        "schema_version": "1.0",
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "mode": "reset" if args.reset else "readonly",
        "sync_strategy": "host_clock_sync",
        "note": "TimestampReset clears per-camera free-running counter; not wall-clock sync",
        "reset_supported_all": reset_supported and not any_fail,
        "cameras": cameras_json,
    }

    out = args.output
    if out is None:
        name = "timestamp_reset.json" if args.reset else "timestamp_report.json"
        out = ensure_dir(settings.healthcheck_output_dir) / name
    else:
        ensure_dir(out.parent)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    logger.info(
        "timestamp_test done reset_supported_all=%s any_fail=%s out=%s",
        doc["reset_supported_all"],
        any_fail,
        out,
    )
    print(json.dumps(doc, indent=2, ensure_ascii=False))
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
