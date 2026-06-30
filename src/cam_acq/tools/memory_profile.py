#!/usr/bin/env python3
"""Phase 4.9: measure pre-buffer ring RAM and host/GPU memory during 2ch grab + encode."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from cam_acq.detection.gst_live import DeepStreamYoloLive  # noqa: F401 — gi before gxipy

from cam_acq.camera.timesync import TimeSyncManager
from cam_acq.config import NOMINAL_FPS, load_settings, setup_galaxy_lib_path
from cam_acq.detection.events import RecordingTrigger
from cam_acq.monitoring.host_metrics import HostMetricsSampler
from cam_acq.monitoring.payloads import prebuffer_payload
from cam_acq.recording.buffer import ring_capacity_frames
from cam_acq.recording.controller import RecordingController
from cam_acq.recording.grab import run_camera_grab_loop
from cam_acq.recording.storage import StorageManager


def memory_profile_schedule(buffer_sec: float) -> tuple[float, float]:
    """Soak until rings fill, then manual trigger with post-buffer margin."""
    soak_sec = buffer_sec * 3 + 5
    trigger_at_sec = soak_sec
    duration_sec = soak_sec + buffer_sec * 2 + 10
    return duration_sec, trigger_at_sec


def _sample_dict(sampler: HostMetricsSampler) -> dict[str, Any]:
    """Flatten one host metrics snapshot for JSON logging."""
    snap = sampler.sample_once()
    out: dict[str, Any] = {
        "collected_at": snap.collected_at,
        "cpu_percent": snap.cpu.percent,
        "ram_used_bytes": snap.memory.used_bytes,
        "ram_total_bytes": snap.memory.total_bytes,
        "ram_percent": snap.memory.percent,
        "process_rss_bytes": snap.process.rss_bytes if snap.process else None,
    }
    if snap.gpu is not None:
        out.update(
            {
                "gpu_util_percent": snap.gpu.utilization_percent,
                "gpu_encoder_percent": snap.gpu.encoder_percent,
                "vram_used_mb": snap.gpu.memory_used_mb,
                "vram_total_mb": snap.gpu.memory_total_mb,
                "gpu_temp_c": snap.gpu.temperature_c,
            }
        )
    return out


def _peak_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Peak numeric fields across timed samples."""

    def _peak(key: str) -> int | float | None:
        vals = [s[key] for s in samples if s.get(key) is not None]
        return max(vals) if vals else None

    return {
        "sample_count": len(samples),
        "ram_used_bytes_peak": _peak("ram_used_bytes"),
        "ram_percent_peak": _peak("ram_percent"),
        "process_rss_bytes_peak": _peak("process_rss_bytes"),
        "vram_used_mb_peak": _peak("vram_used_mb"),
        "gpu_util_percent_peak": _peak("gpu_util_percent"),
        "gpu_encoder_percent_peak": _peak("gpu_encoder_percent"),
    }


def run_memory_profile(
    *,
    duration_sec: float,
    trigger_at_sec: float,
    poll_sec: float,
    env_file: Path | None,
    output_json: Path | None,
) -> int:
    """2ch Bayer ring soak, optional trigger encode, RAM/VRAM peak sampling."""
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

    sampler = HostMetricsSampler(gpu_index=settings.gpu_id, poll_sec=poll_sec)
    samples: list[dict[str, Any]] = []
    phase = "soak"
    errors: list[str] = []
    stop_at = time.monotonic() + duration_sec
    trigger_at = time.monotonic() + trigger_at_sec
    decision = None
    segments: list[Any] = []

    def _grab(cam_ip: str, cam_index: int) -> None:
        try:
            run_camera_grab_loop(
                ip=cam_ip,
                camera_index=cam_index,
                stop_at=stop_at,
                controller=controller,
                errors=errors,
            )
        except Exception:
            pass

    threads = [
        threading.Thread(
            target=_grab,
            kwargs={"cam_ip": cam.ip, "cam_index": cam.index},
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
        sample = _sample_dict(sampler)
        sample["phase"] = phase
        sample["ring_memory_bytes"] = controller.memory_report()
        samples.append(sample)

        now = time.monotonic()
        if decision is None and now >= trigger_at:
            action = trigger.manual_start()
            controller.apply_trigger_action(action)
            decision = action.decision
            phase = "manual_recording"

        if decision is not None and not manual_stopped and now >= stop_manual_at:
            controller.apply_trigger_action(trigger.manual_stop())
            manual_stopped = True
            phase = "trigger_post_buffer"

        if controller.session_active:
            controller.maybe_flush_incremental(time_sync=time_sync)

        if manual_stopped and controller.pending_ready() and phase != "encoding":
            phase = "encoding"
            encode_sample = _sample_dict(sampler)
            encode_sample["phase"] = "encoding_start"
            encode_sample["ring_memory_bytes"] = controller.memory_report()
            samples.append(encode_sample)
            segments = controller.flush_pending(time_sync=time_sync)
            encode_end = _sample_dict(sampler)
            encode_end["phase"] = "encoding_end"
            encode_end["ring_memory_bytes"] = controller.memory_report()
            samples.append(encode_end)
            phase = "post_encode"

        time.sleep(poll_sec)

    for t in threads:
        t.join(timeout=5.0)

    peaks = _peak_summary(samples)
    prebuffer = prebuffer_payload(settings, controller)
    ring_measured = controller.memory_report()
    cap = ring_capacity_frames(NOMINAL_FPS, settings.recording_buffer_sec)

    ring_stats = controller.ring_stats_report()
    report = {
        "schema_version": "1.0",
        "status": (
            "PASS"
            if ring_measured and not errors and ring_stats.get("healthy", True)
            else "FAIL"
        ),
        "phase": "4.9_memory_profile",
        "num_cameras": settings.num_cameras,
        "duration_sec": duration_sec,
        "trigger_at_sec": trigger_at_sec,
        "buffer_sec": settings.recording_buffer_sec,
        "codec": settings.encoding_codec,
        "resolution": f"{settings.camera_width}x{settings.camera_height}",
        "ring_capacity_frames": cap,
        "prebuffer": prebuffer,
        "ring_memory_bytes": ring_measured,
        "ring_memory_bytes_total": sum(ring_measured.values()),
        "ring_stats": ring_stats,
        "peaks": peaks,
        "encode_triggered": decision is not None,
        "segments_written": len(segments),
        "samples": samples,
        "errors": errors,
    }
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4.9 RAM/VRAM measurement (2ch ring + encode)")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--trigger-at", type=float, default=None)
    parser.add_argument("--poll-sec", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=Path("healthcheck/memory_profile.json"))
    args = parser.parse_args()
    settings = load_settings(args.env_file)
    default_duration, default_trigger = memory_profile_schedule(settings.recording_buffer_sec)
    duration = default_duration if args.duration is None else args.duration
    trigger_at = default_trigger if args.trigger_at is None else args.trigger_at
    if duration < trigger_at + settings.recording_buffer_sec:
        print("duration too short for trigger + post-buffer", file=sys.stderr)
        return 1
    return run_memory_profile(
        duration_sec=duration,
        trigger_at_sec=trigger_at,
        poll_sec=args.poll_sec,
        env_file=args.env_file,
        output_json=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
