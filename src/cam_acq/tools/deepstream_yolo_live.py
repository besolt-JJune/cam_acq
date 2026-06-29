#!/usr/bin/env python3
"""Live 2ch GigE → DeepStream YOLO (appsrc) with optional overlay MP4 and event recording."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# gi (via gst_live) must load before numpy (frame/gst_live use numpy after gi init)
from cam_acq.detection.gst_live import DeepStreamYoloLive
from cam_acq.detection.gst_meta import LiveDetectionBridge

from cam_acq.camera.frame import BayerFrame, DebayerBackend
from cam_acq.camera.bayer import gst_format_from_bayer_format
from cam_acq.camera.timesync import SessionTimeSync, TimeSyncManager
from cam_acq.config import NOMINAL_FPS, load_settings, project_root, setup_galaxy_lib_path
from cam_acq.detection.events import RecordingTrigger
from cam_acq.recording.controller import RecordedSegment, RecordingController
from cam_acq.recording.grab import run_camera_grab_loop
from cam_acq.recording.storage import StorageManager

import numpy as np


@dataclass
class LiveFeedStats:
    """Per-camera grab stats for live DeepStream test."""

    camera_index: int
    ip: str
    frames_grabbed: int = 0
    frames_pushed: int = 0
    incomplete_frames: int = 0
    open_error: str | None = None
    _latest_rgb: np.ndarray | None = field(default=None, repr=False)
    _latest_bayer: BayerFrame | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_latest_rgb(self, frame: np.ndarray) -> None:
        with self._lock:
            self._latest_rgb = frame

    def take_latest_rgb(self) -> np.ndarray | None:
        with self._lock:
            return self._latest_rgb

    def set_latest_bayer(self, frame: BayerFrame) -> None:
        with self._lock:
            self._latest_bayer = frame

    def take_latest_bayer(self) -> BayerFrame | None:
        with self._lock:
            return self._latest_bayer


def _grab_thread(
    *,
    ip: str,
    stats: LiveFeedStats,
    controller: RecordingController | None,
    stop_at: float,
    resize_w: int,
    resize_h: int,
    debayer_backend: DebayerBackend,
    bayer_format: str,
    errors: list[str],
) -> None:
    """One camera: Bayer ring (optional) + latest frame for DeepStream (RGB or Bayer)."""
    use_gpu_debayer = debayer_backend == DebayerBackend.GPU_PHASE3

    def on_rgb(rgb: np.ndarray) -> None:
        stats.frames_grabbed += 1
        stats.set_latest_rgb(rgb)

    def on_bayer(bayer: BayerFrame) -> None:
        stats.frames_grabbed += 1
        stats.set_latest_bayer(bayer)

    try:
        run_camera_grab_loop(
            ip=ip,
            camera_index=stats.camera_index,
            stop_at=stop_at,
            controller=controller,
            on_rgb_frame=None if use_gpu_debayer else on_rgb,
            on_bayer_frame=on_bayer if use_gpu_debayer else None,
            resize_w=resize_w,
            resize_h=resize_h,
            debayer_backend=debayer_backend,
            bayer_format=bayer_format,
            errors=errors,
        )
    except Exception as exc:
        stats.open_error = str(exc)


def _segments_to_report(segments: list[RecordedSegment]) -> list[dict]:
    return [
        {
            "camera_index": s.camera_index,
            "segment_index": s.segment_index,
            "video": str(s.video_path),
            "session": str(s.session_path),
            "frames": str(s.frames_path),
            "frame_count": s.frame_count,
        }
        for s in segments
    ]


def _flush_ready_segments(
    controller: RecordingController,
    time_sync: SessionTimeSync,
) -> list[RecordedSegment]:
    """Encode and clear pending trigger when post-buffer elapsed."""
    if not controller.pending_ready():
        return []
    return controller.flush_pending(time_sync=time_sync)


def run_live(
    *,
    duration_sec: float,
    env_file: Path | None,
    record_path: Path | None,
    output_json: Path | None,
    event_recording: bool,
) -> int:
    """Grab from configured cameras, run YOLO, optionally NVENC on person trigger."""
    settings = load_settings(env_file)
    root = project_root()
    nvinfer = root / "configs" / "nvinfer" / "config_infer_primary_yolo.txt"
    if not nvinfer.is_file():
        print(f"Missing nvinfer config: {nvinfer}", file=sys.stderr)
        return 1
    engine = settings.detection_model_path
    if not engine.is_absolute():
        engine = root / engine
    if not engine.is_file():
        print(f"Missing TensorRT engine: {engine} (run cam-acq-build-yolo)", file=sys.stderr)
        return 1

    if settings.debayer_backend not in (
        DebayerBackend.CPU_SDK,
        DebayerBackend.GPU_PHASE3,
    ):
        print(
            f"DEBAYER_MODE={settings.debayer_backend.value} is not supported for yolo-live",
            file=sys.stderr,
        )
        return 1

    use_gpu_debayer = settings.debayer_backend == DebayerBackend.GPU_PHASE3

    storage: StorageManager | None = None
    controller: RecordingController | None = None
    time_sync: SessionTimeSync | None = None
    recorded_segments: list[RecordedSegment] = []

    if event_recording:
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
        time_sync = TimeSyncManager().begin_session(
            settings.cameras,
            timestamp_reset=settings.timestamp_reset_on_session,
        )

    trigger = RecordingTrigger(
        buffer_sec=settings.recording_buffer_sec,
        confidence_threshold=settings.detection_confidence,
        camera_indices=settings.camera_indices,
    )
    stats_list = [LiveFeedStats(camera_index=c.index, ip=c.ip) for c in settings.cameras]
    cam_w = settings.camera_width or 3840
    cam_h = settings.camera_height or 2160
    detection_bridge = LiveDetectionBridge(
        resize_w=settings.resize_width,
        resize_h=settings.resize_height,
        camera_w=cam_w,
        camera_h=cam_h,
        confidence_threshold=settings.detection_confidence,
        trigger=trigger,
        recording=controller,
    )

    stop_at = time.monotonic() + duration_sec
    grab_errors: list[str] = []
    threads = [
        threading.Thread(
            target=_grab_thread,
            kwargs={
                "ip": st.ip,
                "stats": st,
                "controller": controller,
                "stop_at": stop_at,
                "resize_w": settings.resize_width,
                "resize_h": settings.resize_height,
                "debayer_backend": settings.debayer_backend,
                "bayer_format": settings.bayer_format,
                "errors": grab_errors,
            },
            daemon=True,
        )
        for st in stats_list
    ]
    for t in threads:
        t.start()
    time.sleep(1.0)
    for st in stats_list:
        if st.open_error:
            print(f"cam{st.camera_index} open failed: {st.open_error}", file=sys.stderr)
            return 1

    pipeline = DeepStreamYoloLive(
        num_cameras=settings.num_cameras,
        width=settings.resize_width,
        height=settings.resize_height,
        fps=NOMINAL_FPS,
        gpu_id=settings.gpu_id,
        nvinfer_config=nvinfer,
        record_path=record_path,
        detection_bridge=detection_bridge,
        bayer_input=use_gpu_debayer,
        bayer_width=cam_w,
        bayer_height=cam_h,
        bayer_gst_format=gst_format_from_bayer_format(settings.bayer_format),
    )
    pipeline.start()
    started_wall = time.time()
    started = time.monotonic()
    push_errors = 0
    try:
        while time.monotonic() < stop_at:
            if use_gpu_debayer:
                bayer_batch: list[BayerFrame] = []
                for st in stats_list:
                    frame = st.take_latest_bayer()
                    if frame is None:
                        break
                    bayer_batch.append(frame)
                if len(bayer_batch) != settings.num_cameras:
                    time.sleep(0.001)
                    err = pipeline.poll_bus_errors()
                    if err:
                        print(f"pipeline error: {err}", file=sys.stderr)
                        return 1
                    continue
                try:
                    pipeline.push_bayer_batch(bayer_batch)
                    for st in stats_list:
                        st.frames_pushed += 1
                except RuntimeError as exc:
                    push_errors += 1
                    print(f"push error: {exc}", file=sys.stderr)
                    if push_errors > 5:
                        return 1
            else:
                batch: list[np.ndarray] = []
                for st in stats_list:
                    frame = st.take_latest_rgb()
                    if frame is None:
                        break
                    batch.append(frame)
                if len(batch) != settings.num_cameras:
                    time.sleep(0.001)
                    err = pipeline.poll_bus_errors()
                    if err:
                        print(f"pipeline error: {err}", file=sys.stderr)
                        return 1
                    continue
                try:
                    pipeline.push_batch(batch)
                    for st in stats_list:
                        st.frames_pushed += 1
                except RuntimeError as exc:
                    push_errors += 1
                    print(f"push error: {exc}", file=sys.stderr)
                    if push_errors > 5:
                        return 1
            err = pipeline.poll_bus_errors()
            if err:
                print(f"pipeline error: {err}", file=sys.stderr)
                return 1
            if controller is not None and time_sync is not None:
                recorded_segments.extend(_flush_ready_segments(controller, time_sync))
            time.sleep(1.0 / NOMINAL_FPS)
    finally:
        pipeline.stop()
        for t in threads:
            t.join(timeout=5.0)
        if controller is not None and time_sync is not None:
            post_deadline = time.monotonic() + settings.recording_buffer_sec + 2.0
            while time.monotonic() < post_deadline:
                if not controller.pending_ready():
                    time.sleep(0.05)
                    continue
                recorded_segments.extend(_flush_ready_segments(controller, time_sync))
                break
            else:
                recorded_segments.extend(_flush_ready_segments(controller, time_sync))

    elapsed = time.monotonic() - started
    report: dict = {
        "schema_version": "1.0",
        "status": "PASS",
        "duration_sec": round(elapsed, 3),
        "num_cameras": settings.num_cameras,
        "event_recording": event_recording,
        "resize": {
            "width": settings.resize_width,
            "height": settings.resize_height,
        },
        "debayer_backend": settings.debayer_backend.value,
        "detection": detection_bridge.snapshot(),
        "nvinfer_config": str(nvinfer),
        "engine": str(engine),
        "record_path": str(record_path) if record_path else None,
        "cameras": [
            {
                "camera_index": st.camera_index,
                "ip": st.ip,
                "frames_grabbed": st.frames_grabbed,
                "frames_pushed": st.frames_pushed,
                "incomplete_frames": st.incomplete_frames,
                "fps_pushed_avg": round(st.frames_pushed / elapsed, 2) if elapsed > 0 else 0.0,
                "open_error": st.open_error,
            }
            for st in stats_list
        ],
        "started_at": datetime.fromtimestamp(started_wall, tz=timezone.utc).isoformat(),
    }
    if event_recording and storage is not None and controller is not None:
        report["recording"] = {
            "buffer_sec": settings.recording_buffer_sec,
            "codec": settings.encoding_codec,
            "storage": {
                "path": str(storage.location.path),
                "is_fallback": storage.location.is_fallback,
                "primary_path": str(settings.storage_path),
                "primary_reject_reason": storage.primary_reject_reason,
            },
            "ring_memory_bytes": controller.memory_report(),
            "segments": _segments_to_report(recorded_segments),
        }
        if not recorded_segments and detection_bridge.trigger_decisions:
            report["status"] = "FAIL"
        if grab_errors:
            report["status"] = "FAIL"
            report["recording"]["grab_errors"] = grab_errors

    min_pushed = int(duration_sec * NOMINAL_FPS * 0.8)
    for cam in report["cameras"]:
        if cam["frames_pushed"] < min_pushed:
            report["status"] = "FAIL"
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Live GigE → DeepStream YOLO (2ch)")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--duration", type=float, default=30.0, help="seconds")
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        help="overlay MP4 path (default: ./samples/deepstream_yolo_overlay_live_2ch.mp4)",
    )
    parser.add_argument("--no-record", action="store_true", help="fakesink only, no overlay MP4")
    parser.add_argument(
        "--no-event-recording",
        action="store_true",
        help="disable Phase 4 NVENC recording on person trigger",
    )
    parser.add_argument("--output", type=Path, default=None, help="JSON report path")
    args = parser.parse_args()

    setup_galaxy_lib_path()
    record = None if args.no_record else (args.record or Path("samples/deepstream_yolo_overlay_live_2ch.mp4"))
    return run_live(
        duration_sec=args.duration,
        env_file=args.env_file,
        record_path=record,
        output_json=args.output,
        event_recording=not args.no_event_recording,
    )


if __name__ == "__main__":
    raise SystemExit(main())
