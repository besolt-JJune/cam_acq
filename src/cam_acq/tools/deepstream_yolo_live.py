#!/usr/bin/env python3
"""Live 2ch GigE → DeepStream YOLO (appsrc) with optional overlay MP4."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from cam_acq.camera.device import close_camera, open_camera_by_ip
from cam_acq.camera.frame import DebayerBackend, raw_image_to_frame
from cam_acq.config import NOMINAL_FPS, load_settings, project_root, setup_galaxy_lib_path
from cam_acq.detection.events import RecordingTrigger
from cam_acq.detection.gst_live import DeepStreamYoloLive
from cam_acq.detection.gst_meta import LiveDetectionBridge
from gxipy.gxidef import GxFrameStatusList, GxSwitchEntry


@dataclass
class LiveFeedStats:
    """Per-camera grab stats for live DeepStream test."""

    camera_index: int
    ip: str
    frames_grabbed: int = 0
    frames_pushed: int = 0
    incomplete_frames: int = 0
    open_error: str | None = None
    _latest: np.ndarray | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_latest(self, frame: np.ndarray) -> None:
        with self._lock:
            self._latest = frame

    def take_latest(self) -> np.ndarray | None:
        with self._lock:
            return self._latest


def _grab_thread(
    *,
    ip: str,
    stats: LiveFeedStats,
    stop_at: float,
    resize_w: int,
    resize_h: int,
    debayer_backend: DebayerBackend,
) -> None:
    """Continuous grab; keep latest resized RGB frame."""
    cam = None
    try:
        cam = open_camera_by_ip(ip)
        cam.TriggerMode.set(GxSwitchEntry.OFF)
        cam.stream_on()
        while time.monotonic() < stop_at:
            raw = cam.data_stream[0].get_image(timeout=1000)
            if raw is None:
                continue
            stats.frames_grabbed += 1
            if raw.get_status() != GxFrameStatusList.SUCCESS:
                stats.incomplete_frames += 1
                continue
            rgb = raw_image_to_frame(raw, resize_w, resize_h, backend=debayer_backend)
            if rgb is not None:
                stats.set_latest(rgb)
    except Exception as exc:
        stats.open_error = str(exc)
    finally:
        if cam is not None:
            try:
                cam.stream_off()
            except Exception:
                pass
        close_camera(cam)


def run_live(
    *,
    duration_sec: float,
    env_file: Path | None,
    record_path: Path | None,
    output_json: Path | None,
) -> int:
    """Grab from configured cameras and run DeepStream YOLO for duration_sec."""
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

    if settings.debayer_backend != DebayerBackend.CPU_SDK:
        print(
            f"DEBAYER_MODE={settings.debayer_backend.value} is not implemented yet "
            f"(see docs/11_field_pending_work.md §6)",
            file=sys.stderr,
        )
        return 1

    stats_list = [LiveFeedStats(camera_index=c.index, ip=c.ip) for c in settings.cameras]
    cam_w = settings.camera_width or 3840
    cam_h = settings.camera_height or 2160
    detection_bridge = LiveDetectionBridge(
        resize_w=settings.resize_width,
        resize_h=settings.resize_height,
        camera_w=cam_w,
        camera_h=cam_h,
        confidence_threshold=settings.detection_confidence,
        trigger=RecordingTrigger(
            buffer_sec=settings.recording_buffer_sec,
            confidence_threshold=settings.detection_confidence,
            camera_indices=settings.camera_indices,
        ),
    )
    stop_at = time.monotonic() + duration_sec
    threads = [
        threading.Thread(
            target=_grab_thread,
            kwargs={
                "ip": st.ip,
                "stats": st,
                "stop_at": stop_at,
                "resize_w": settings.resize_width,
                "resize_h": settings.resize_height,
                "debayer_backend": settings.debayer_backend,
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
    )
    pipeline.start()
    started_wall = time.time()
    started = time.monotonic()
    push_errors = 0
    try:
        while time.monotonic() < stop_at:
            batch: list[np.ndarray] = []
            for st in stats_list:
                frame = st.take_latest()
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
            time.sleep(1.0 / NOMINAL_FPS)
    finally:
        pipeline.stop()
        for t in threads:
            t.join(timeout=5.0)

    elapsed = time.monotonic() - started
    report = {
        "schema_version": "1.0",
        "status": "PASS",
        "duration_sec": round(elapsed, 3),
        "num_cameras": settings.num_cameras,
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
    parser.add_argument("--no-record", action="store_true", help="fakesink only, no MP4")
    parser.add_argument("--output", type=Path, default=None, help="JSON report path")
    args = parser.parse_args()

    setup_galaxy_lib_path()
    record = None if args.no_record else (args.record or Path("samples/deepstream_yolo_overlay_live_2ch.mp4"))
    return run_live(
        duration_sec=args.duration,
        env_file=args.env_file,
        record_path=record,
        output_json=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
