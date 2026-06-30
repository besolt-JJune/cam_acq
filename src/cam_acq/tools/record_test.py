#!/usr/bin/env python3
"""Phase 4 manual trigger recording test (2ch Bayer ring → NVENC MP4)."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

# gi + numpy init order (see deepstream_yolo_live.py)
from cam_acq.detection.gst_live import DeepStreamYoloLive  # noqa: F401

from cam_acq.camera.timesync import TimeSyncManager
from cam_acq.camera.param_store import RuntimeParamStore
from cam_acq.config import NOMINAL_FPS, load_settings, setup_galaxy_lib_path
from cam_acq.detection.events import RecordingTrigger
from cam_acq.recording.controller import RecordingController
from cam_acq.recording.grab import run_camera_grab_loop
from cam_acq.recording.storage import StorageManager


def _run_grab(
    *,
    ip: str,
    camera_index: int,
    controller: RecordingController,
    stop_at: float,
    param_store: RuntimeParamStore | None,
    errors: list[str],
) -> None:
    """Thread target: Bayer-only grab into recording ring."""
    try:
        run_camera_grab_loop(
            ip=ip,
            camera_index=camera_index,
            stop_at=stop_at,
            controller=controller,
            param_store=param_store,
            errors=errors,
        )
    except Exception:
        pass


def run_record_test(
    *,
    duration_sec: float,
    trigger_at_sec: float,
    env_file: Path | None,
    output_json: Path | None,
    with_monitoring: bool = False,
) -> int:
    """Fill rings, fire manual trigger, encode after post-buffer."""
    settings = load_settings(env_file)
    setup_galaxy_lib_path()

    storage = StorageManager(
        settings.storage_path,
        settings.storage_path_sub,
        management=settings.storage_management,
        full_percentage=settings.storage_full_percentage,
    )
    controller = RecordingController(
        storage=storage,
        camera_indices=settings.camera_indices,
        buffer_sec=settings.recording_buffer_sec,
        split_interval_sec=settings.recording_split_interval_sec,
        pixel_format=settings.pixel_format,
        bayer_format=settings.bayer_format,
        codec=settings.encoding_codec,
        bitrate_bps=int(settings.encoding_bitrate_mbps * 1_000_000),
        gpu_id=settings.gpu_id,
    )
    trigger = RecordingTrigger(
        buffer_sec=settings.recording_buffer_sec,
        confidence_threshold=settings.detection_confidence,
        camera_indices=settings.camera_indices,
    )

    time_sync = TimeSyncManager().begin_session(
        settings.cameras,
        timestamp_reset=settings.timestamp_reset_on_session,
    )

    param_store: RuntimeParamStore | None = None
    if with_monitoring:
        from cam_acq.monitoring import DashboardCollector, PipelineHooks, start_monitoring_server

        param_store = RuntimeParamStore(settings.camera_indices)
        hooks = PipelineHooks(param_store=param_store)
        hooks.bind_recording(controller, trigger=trigger)
        hooks.bind_time_sync(time_sync)
        collector = DashboardCollector(settings, hooks=hooks, storage_manager=storage)
        start_monitoring_server(settings, collector)

    stop_at = time.monotonic() + duration_sec
    trigger_at = time.monotonic() + trigger_at_sec
    errors: list[str] = []
    threads = [
        threading.Thread(
            target=_run_grab,
            kwargs={
                "ip": cam.ip,
                "camera_index": cam.index,
                "controller": controller,
                "stop_at": stop_at,
                "param_store": param_store,
                "errors": errors,
            },
            daemon=True,
        )
        for cam in settings.cameras
    ]
    for t in threads:
        t.start()

    decision = None
    manual_stopped = False
    manual_record_sec = max(3.0, settings.recording_buffer_sec)
    stop_manual_at = trigger_at + manual_record_sec
    while time.monotonic() < stop_at:
        now = time.monotonic()
        if decision is None and now >= trigger_at:
            action = trigger.manual_start()
            controller.apply_trigger_action(action)
            decision = action.decision
        if decision is not None and not manual_stopped and now >= stop_manual_at:
            controller.apply_trigger_action(trigger.manual_stop())
            manual_stopped = True
        if controller.session_active:
            controller.maybe_flush_incremental(time_sync=time_sync)
        if manual_stopped and controller.pending_ready():
            break
        time.sleep(0.05)

    for t in threads:
        t.join(timeout=5.0)

    segments = controller.flush_pending(time_sync=time_sync)
    trigger.clear_session()
    if errors:
        print("\n".join(errors), file=sys.stderr)

    ring_stats = controller.ring_stats_report()
    report = {
        "schema_version": "1.0",
        "status": "PASS" if segments and not errors and ring_stats.get("healthy", True) else "FAIL",
        "duration_sec": duration_sec,
        "trigger_at_sec": trigger_at_sec,
        "buffer_sec": settings.recording_buffer_sec,
        "codec": settings.encoding_codec,
        "storage": {
            "path": str(storage.location.path),
            "is_fallback": storage.location.is_fallback,
            "primary_path": str(settings.storage_path),
            "primary_reject_reason": storage.primary_reject_reason,
            "usage_ratio": round(storage.usage_ratio(), 4),
        },
        "ring_memory_bytes": controller.memory_report(),
        "ring_stats": ring_stats,
        "segments": [
            {
                "camera_index": s.camera_index,
                "segment_index": s.segment_index,
                "video": str(s.video_path),
                "session": str(s.session_path),
                "frames": str(s.frames_path),
                "frame_count": s.frame_count,
            }
            for s in segments
        ],
        "trigger": decision.as_dict() if decision else None,
        "time_sync": time_sync.to_dict(),
    }
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual trigger recording test (Phase 4)")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--duration", type=float, default=35.0, help="total grab seconds")
    parser.add_argument(
        "--trigger-at",
        type=float,
        default=10.0,
        help="manual trigger after N seconds",
    )
    parser.add_argument("--output", type=Path, default=Path("healthcheck/record_test.json"))
    parser.add_argument(
        "--with-monitoring",
        action="store_true",
        help="start REST API for runtime camera params (MONITORING_WEB_PORT)",
    )
    args = parser.parse_args()
    if args.duration < args.trigger_at + 3:
        print("duration must allow manual record + encode after stop", file=sys.stderr)
        return 1
    return run_record_test(
        duration_sec=args.duration,
        trigger_at_sec=args.trigger_at,
        env_file=args.env_file,
        output_json=args.output,
        with_monitoring=args.with_monitoring,
    )


if __name__ == "__main__":
    raise SystemExit(main())
