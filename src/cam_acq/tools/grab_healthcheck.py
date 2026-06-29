#!/usr/bin/env python3
"""Soak grab from all configured cameras; write JSON report and exit code."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from cam_acq.camera.grab import GrabStats, min_frames_expected, run_multi_grab
from cam_acq.camera.timesync import SessionTimeSync, TimeSyncManager
from cam_acq.config import NOMINAL_FPS, ensure_dir, load_settings, setup_galaxy_lib_path
from cam_acq.logging_setup import setup_logging


def _save_sample_jpeg(stats: GrabStats, out_dir: Path) -> str | None:
    """Save last frame as JPEG (Bayer→RGB via SDK); return relative path."""
    raw = stats.last_raw_image
    if raw is None:
        return None
    try:
        from PIL import Image

        rgb = raw.convert("RGB")
        if rgb is None:
            return None
        arr = rgb.get_numpy_array()
        if arr is None:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"cam{stats.camera_index}_last.jpg"
        Image.fromarray(arr, "RGB").save(path, quality=85)
        return str(path)
    except Exception:
        return None


def _camera_pass(
    st: GrabStats,
    duration_sec: float,
    min_fps: float,
) -> tuple[bool, list[str]]:
    """Return (ok, reasons)."""
    reasons: list[str] = []
    if st.open_error:
        reasons.append(f"open_error: {st.open_error}")
        return False, reasons
    if st.fps_avg < min_fps:
        reasons.append(f"fps_avg {st.fps_avg:.2f} < {min_fps}")
    if st.frame_drops > 0:
        reasons.append(f"frame_drops={st.frame_drops}")
    if st.incomplete_frames > 0:
        reasons.append(f"incomplete_frames={st.incomplete_frames}")
    exp = min_frames_expected(duration_sec)
    if st.frames_received < exp:
        reasons.append(f"frames_received {st.frames_received} < {exp}")
    return len(reasons) == 0, reasons


def build_report(
    stats_list: list[GrabStats],
    duration_sec: float,
    min_fps: float,
    num_configured: int,
    sample_dir: Path | None,
    time_sync: SessionTimeSync | None = None,
    include_recovery: bool = False,
) -> dict:
    """Build healthcheck JSON document."""
    cameras_out = []
    all_ok = True
    for st in stats_list:
        ok, reasons = _camera_pass(st, duration_sec, min_fps)
        if not ok:
            all_ok = False
        sample_path = None
        if sample_dir is not None:
            sample_path = _save_sample_jpeg(st, sample_dir)
        cameras_out.append(
            {
                "camera_index": st.camera_index,
                "ip": st.ip,
                "width": st.width,
                "height": st.height,
                "pixel_format": st.pixel_format,
                "frames_received": st.frames_received,
                "fps_avg": round(st.fps_avg, 3),
                "fps_min": round(st.fps_min, 3),
                "frame_drops": st.frame_drops,
                "incomplete_frames": st.incomplete_frames,
                "timestamp_monotonic": st.timestamp_monotonic,
                "sample_image": sample_path,
                "pass": ok,
                "fail_reasons": reasons,
                **(
                    {
                        "recovery": {
                            "offline_events": st.recovery.offline_events,
                            "reconnect_success": st.recovery.reconnect_success,
                            "reconnect_failed": st.recovery.reconnect_failed,
                            "last_reconnect_error": st.recovery.last_reconnect_error,
                        }
                    }
                    if include_recovery
                    else {}
                ),
            }
        )

    if len(stats_list) < num_configured:
        all_ok = False

    doc = {
        "schema_version": "1.0",
        "status": "PASS" if all_ok else "FAIL",
        "duration_sec": duration_sec,
        "num_cameras_configured": num_configured,
        "num_cameras_active": len(stats_list),
        "criteria": {
            "min_fps": min_fps,
            "nominal_fps": NOMINAL_FPS,
            "max_frame_drops": 0,
            "max_incomplete_frames": 0,
            "min_frames_ratio": 0.95,
        },
        "cameras": cameras_out,
        "summary": "All cameras passed stability check."
        if all_ok
        else "One or more cameras failed criteria.",
    }
    if time_sync is not None:
        doc["time_sync"] = time_sync.to_dict()
        skew = time_sync.max_cross_camera_skew_us
        tol_us = time_sync.cross_camera_skew_tolerance_ms * 1000
        if skew is not None and skew > tol_us:
            doc["time_sync_warning"] = (
                f"max_cross_camera_skew_us {skew} > tolerance {tol_us}"
            )
    return doc


def main(argv: list[str] | None = None) -> int:
    """CLI entry: 0=PASS, 1=FAIL, 2=config/environment error."""
    parser = argparse.ArgumentParser(description="Camera grab stability healthcheck")
    parser.add_argument("--duration", type=float, default=60.0, help="Soak seconds")
    parser.add_argument("--min-fps", type=float, default=22.0, help="PASS min avg FPS")
    parser.add_argument("--output", type=Path, default=None, help="JSON report path")
    parser.add_argument("--save-sample", type=Path, default=None, help="JPEG sample dir")
    parser.add_argument("--log", type=Path, default=None, help="LOG_PATH override")
    parser.add_argument(
        "--no-timestamp-reset",
        action="store_true",
        help="Skip TimestampReset at session start (default: reset per TIMESTAMP_RESET_ON_SESSION)",
    )
    parser.add_argument(
        "--recovery",
        action="store_true",
        help="Enable GigE offline callback + IP reconnect during soak",
    )
    args = parser.parse_args(argv)

    try:
        setup_galaxy_lib_path()
        settings = load_settings()
    except Exception as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    log_dir = args.log or settings.log_path
    logger = setup_logging(log_dir)
    out_path = args.output or (ensure_dir(settings.healthcheck_output_dir) / "report.json")
    ensure_dir(out_path.parent)

    logger.info(
        "healthcheck start duration=%s cameras=%s",
        args.duration,
        settings.num_cameras,
    )

    fallback_w = settings.camera_width or 3840
    fallback_h = settings.camera_height or 2160

    timestamp_reset = settings.timestamp_reset_on_session and not args.no_timestamp_reset
    time_sync = TimeSyncManager().begin_session(
        settings.cameras,
        timestamp_reset=timestamp_reset,
        cross_camera_skew_tolerance_ms=settings.cross_camera_skew_tolerance_ms,
    )
    for a in time_sync.anchors:
        if a.open_error or a.reset_error:
            logger.warning(
                "time_sync cam%s ip=%s open_error=%s reset_error=%s",
                a.camera_index,
                a.ip,
                a.open_error,
                a.reset_error,
            )
    if time_sync.max_cross_camera_skew_us is not None:
        logger.info(
            "time_sync skew_us=%s tolerance_ms=%s",
            time_sync.max_cross_camera_skew_us,
            settings.cross_camera_skew_tolerance_ms,
        )

    started = datetime.now(timezone.utc)
    stats_list = run_multi_grab(
        settings.cameras,
        args.duration,
        settings.pixel_format,
        fallback_w,
        fallback_h,
        enable_recovery=args.recovery,
        feature_backup_dir=ensure_dir(settings.gige_feature_backup_dir),
        recovery_retry_sec=settings.gige_recovery_retry_sec,
        recovery_max_attempts=settings.gige_recovery_max_attempts,
    )

    report = build_report(
        stats_list,
        args.duration,
        args.min_fps,
        settings.num_cameras,
        args.save_sample,
        time_sync=time_sync,
        include_recovery=args.recovery,
    )
    report["started_at"] = started.isoformat()
    report["ended_at"] = datetime.now(timezone.utc).isoformat()
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for cam in report["cameras"]:
        logger.info(
            "cam%s ip=%s fps_avg=%s drops=%s incomplete=%s pass=%s",
            cam["camera_index"],
            cam["ip"],
            cam["fps_avg"],
            cam["frame_drops"],
            cam["incomplete_frames"],
            cam["pass"],
        )
    logger.info("healthcheck %s report=%s", report["status"], out_path)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
