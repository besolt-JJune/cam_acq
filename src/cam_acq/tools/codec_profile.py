#!/usr/bin/env python3
"""Phase 4.6: encode the same cam0 Bayer window with H.264 vs H.265 for comparison."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from cam_acq.detection.gst_live import DeepStreamYoloLive  # noqa: F401 — gi before gxipy

from cam_acq.camera.timesync import TimeSyncManager
from cam_acq.config import NOMINAL_FPS, load_settings, setup_galaxy_lib_path
from cam_acq.detection.events import RecordingTrigger
from cam_acq.recording.controller import RecordingController
from cam_acq.recording.grab import run_camera_grab_loop
from cam_acq.recording.gst_encode import encode_bayer_frames_to_mp4
from cam_acq.recording.storage import StorageManager


def _nvml_snapshot(gpu_id: int) -> dict[str, int | str]:
    """Sample GPU util and VRAM via NVML; empty dict if unavailable."""
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_id)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        enc_util = 0
        try:
            enc_util, _ = pynvml.nvmlDeviceGetEncoderUtilization(handle)
        except pynvml.NVMLError:
            pass
        return {
            "gpu_util_pct": int(util.gpu),
            "encoder_util_pct": int(enc_util),
            "vram_used_mb": int(mem.used // (1024 * 1024)),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _ffprobe_summary(path: Path) -> dict[str, str | int | float] | None:
    """Return codec and bitrate from ffprobe when installed."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,bit_rate,width,height,avg_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            text=True,
        )
        data = json.loads(out)
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        return {
            "codec_name": s.get("codec_name", ""),
            "bit_rate": int(s.get("bit_rate") or 0),
            "width": int(s.get("width") or 0),
            "height": int(s.get("height") or 0),
            "avg_frame_rate": s.get("avg_frame_rate", ""),
        }
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def _encode_profile(
    frames: list,
    *,
    output_path: Path,
    pixel_format: str,
    fps: float,
    codec: str,
    bitrate_bps: int,
    gpu_id: int,
) -> dict[str, object]:
    """Encode one codec variant and collect timing, size, and GPU samples."""
    samples: list[dict[str, int | str]] = []
    stop = threading.Event()

    def _sampler() -> None:
        while not stop.wait(0.2):
            snap = _nvml_snapshot(gpu_id)
            if "error" not in snap:
                samples.append(snap)

    sampler = threading.Thread(target=_sampler, daemon=True)
    gpu_before = _nvml_snapshot(gpu_id)
    sampler.start()
    t0 = time.perf_counter()
    encode_bayer_frames_to_mp4(
        frames,
        output_path=output_path,
        pixel_format=pixel_format,
        fps=fps,
        codec=codec,
        bitrate_bps=bitrate_bps,
        gpu_id=gpu_id,
    )
    encode_sec = time.perf_counter() - t0
    stop.set()
    sampler.join(timeout=1.0)
    gpu_after = _nvml_snapshot(gpu_id)
    size_bytes = output_path.stat().st_size if output_path.is_file() else 0
    window_sec = max((frames[-1].host_recv_us - frames[0].host_recv_us) / 1_000_000, 1e-6)
    effective_mbps = (size_bytes * 8) / window_sec / 1_000_000

    peak_gpu = max((s.get("gpu_util_pct", 0) for s in samples), default=0)
    peak_enc = max((s.get("encoder_util_pct", 0) for s in samples), default=0)

    return {
        "codec": codec,
        "output": str(output_path),
        "frame_count": len(frames),
        "window_sec": round(window_sec, 3),
        "encode_sec": round(encode_sec, 3),
        "encode_fps": round(len(frames) / encode_sec, 2) if encode_sec > 0 else 0.0,
        "file_bytes": size_bytes,
        "effective_mbps": round(effective_mbps, 3),
        "bitrate_target_mbps": round(bitrate_bps / 1_000_000, 2),
        "gpu_before": gpu_before,
        "gpu_after": gpu_after,
        "gpu_peak_util_pct": peak_gpu,
        "encoder_peak_util_pct": peak_enc,
        "ffprobe": _ffprobe_summary(output_path),
    }


def run_codec_profile(
    *,
    camera_index: int,
    duration_sec: float,
    trigger_at_sec: float,
    codecs: tuple[str, ...],
    bitrate_mbps: float,
    env_file: Path | None,
    output_dir: Path,
    output_json: Path | None,
) -> int:
    """Grab one camera, manual trigger, dual-encode the same window for codec comparison."""
    settings = load_settings(env_file)
    setup_galaxy_lib_path()

    cam = next((c for c in settings.cameras if c.index == camera_index), None)
    if cam is None:
        print(f"camera index {camera_index} not in config", file=sys.stderr)
        return 1

    storage = StorageManager(
        settings.storage_path,
        settings.storage_path_sub,
        management=settings.storage_management,
        full_percentage=settings.storage_full_percentage,
    )
    controller = RecordingController(
        storage=storage,
        camera_indices=(camera_index,),
        buffer_sec=settings.recording_buffer_sec,
        split_interval_sec=settings.recording_split_interval_sec,
        pixel_format=settings.pixel_format,
        codec=settings.encoding_codec,
        bitrate_bps=int(bitrate_mbps * 1_000_000),
        gpu_id=settings.gpu_id,
    )
    trigger = RecordingTrigger(
        buffer_sec=settings.recording_buffer_sec,
        confidence_threshold=settings.detection_confidence,
        camera_indices=(camera_index,),
    )
    TimeSyncManager().begin_session(
        settings.cameras,
        timestamp_reset=settings.timestamp_reset_on_session,
    )

    stop_at = time.monotonic() + duration_sec
    trigger_at = time.monotonic() + trigger_at_sec
    errors: list[str] = []

    def _grab() -> None:
        try:
            run_camera_grab_loop(
                ip=cam.ip,
                camera_index=camera_index,
                stop_at=stop_at,
                controller=controller,
                errors=errors,
            )
        except Exception:
            pass

    thread = threading.Thread(target=_grab, daemon=True)
    thread.start()

    decision = None
    while time.monotonic() < stop_at:
        if decision is None and time.monotonic() >= trigger_at:
            decision = trigger.manual_trigger()
            controller.schedule_trigger(decision)
        if controller.pending_ready():
            break
        time.sleep(0.05)

    thread.join(timeout=5.0)

    taken = controller.take_pending_window_frames()
    if taken is None:
        print("no trigger window captured", file=sys.stderr)
        return 1

    _, frame_map = taken
    frames = frame_map.get(camera_index, [])
    if not frames:
        print("empty frame window", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bitrate_bps = int(bitrate_mbps * 1_000_000)
    runs: list[dict[str, object]] = []
    for codec in codecs:
        out = output_dir / f"{stamp}_cam{camera_index}_{codec}_{int(bitrate_mbps)}mbps.mp4"
        runs.append(
            _encode_profile(
                frames,
                output_path=out,
                pixel_format=settings.pixel_format,
                fps=NOMINAL_FPS,
                codec=codec,
                bitrate_bps=bitrate_bps,
                gpu_id=settings.gpu_id,
            )
        )

    h264 = next((r for r in runs if r["codec"] == "H264"), None)
    h265 = next((r for r in runs if r["codec"] == "H265"), None)
    size_ratio = None
    if h264 and h265 and h264["file_bytes"] and h265["file_bytes"]:
        size_ratio = round(float(h265["file_bytes"]) / float(h264["file_bytes"]), 3)

    report = {
        "schema_version": "1.0",
        "status": "PASS" if runs and not errors else "FAIL",
        "phase": "4.6_codec_profile",
        "camera_index": camera_index,
        "duration_sec": duration_sec,
        "trigger_at_sec": trigger_at_sec,
        "buffer_sec": settings.recording_buffer_sec,
        "bitrate_mbps": bitrate_mbps,
        "resolution": f"{frames[0].width}x{frames[0].height}",
        "h265_vs_h264_size_ratio": size_ratio,
        "encodes": runs,
        "ring_memory_bytes": controller.memory_report(),
        "errors": errors,
    }
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4.6 cam0 codec profile (same Bayer window → H.264 vs H.265)"
    )
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--duration", type=float, default=28.0)
    parser.add_argument("--trigger-at", type=float, default=8.0)
    parser.add_argument("--bitrate-mbps", type=float, default=None, help="default: ENCODING_BITRATE_MBPS")
    parser.add_argument(
        "--codecs",
        nargs="+",
        default=["H264", "H265"],
        choices=["H264", "H265"],
    )
    parser.add_argument("--output-dir", type=Path, default=Path("healthcheck/codec_profile"))
    parser.add_argument("--output", type=Path, default=Path("healthcheck/codec_profile.json"))
    args = parser.parse_args()
    if args.duration < args.trigger_at + 2:
        print("duration must allow pre+post buffer after trigger", file=sys.stderr)
        return 1
    settings = load_settings(args.env_file)
    bitrate = args.bitrate_mbps if args.bitrate_mbps is not None else settings.encoding_bitrate_mbps
    return run_codec_profile(
        camera_index=args.camera_index,
        duration_sec=args.duration,
        trigger_at_sec=args.trigger_at,
        codecs=tuple(args.codecs),
        bitrate_mbps=bitrate,
        env_file=args.env_file,
        output_dir=args.output_dir,
        output_json=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
