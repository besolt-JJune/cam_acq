#!/usr/bin/env python3
"""Probe Galaxy camera PTP GenICam features (Viewer has no PTP UI)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from cam_acq.camera.ptp import PtpCameraReport, probe_ptp_enable_and_poll, probe_ptp_readonly
from cam_acq.config import ensure_dir, load_settings, setup_galaxy_lib_path
from cam_acq.logging_setup import setup_logging


def _report_to_dict(r: PtpCameraReport) -> dict:
    d = asdict(r)
    d["cross_sync_possible"] = None  # filled below
    return d


def main(argv: list[str] | None = None) -> int:
    """CLI: 0=all opened, 1=any open fail, 2=config error."""
    parser = argparse.ArgumentParser(description="PTP feature test via gxipy")
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Set PtpEnable and poll status (default: read-only probe)",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Poll timeout if --enable")
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
    logger.info("ptp_test start enable=%s cameras=%s", args.enable, settings.num_cameras)

    reports: list[PtpCameraReport] = []
    for ep in settings.cameras:
        if args.enable:
            reports.append(probe_ptp_enable_and_poll(ep, timeout_sec=args.timeout))
        else:
            reports.append(probe_ptp_readonly(ep))

    cameras_json = []
    any_open_fail = False
    statuses = []
    for r in reports:
        if r.open_error:
            any_open_fail = True
        if r.ptp_status:
            statuses.append(r.ptp_status)
        cameras_json.append(_report_to_dict(r))

    # 4-port L2-isolated: expect all Master, not Master+Slave pair.
    master_count = sum(1 for s in statuses if s == "Master")
    slave_count = sum(1 for s in statuses if s == "Slave")
    cross_sync = master_count == 1 and slave_count >= 1 and len(statuses) >= 2

    doc = {
        "schema_version": "1.0",
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "mode": "enable_poll" if args.enable else "readonly",
        "topology_note": "4-port NIC direct attach: inter-camera PTP sync unlikely",
        "cross_sync_possible": cross_sync,
        "cameras": cameras_json,
        "recommendation": (
            "host_clock_sync"
            if not cross_sync
            else "ptp_time_sync_manager"
        ),
    }

    out = args.output
    if out is None:
        out = ensure_dir(settings.healthcheck_output_dir) / "ptp_report.json"
    else:
        ensure_dir(out.parent)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    logger.info(
        "ptp_test done cross_sync=%s recommendation=%s out=%s",
        cross_sync,
        doc["recommendation"],
        out,
    )
    print(json.dumps(doc, indent=2, ensure_ascii=False))
    return 1 if any_open_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
