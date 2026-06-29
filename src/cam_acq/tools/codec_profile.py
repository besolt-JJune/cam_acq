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
from cam_acq.detection.events import TriggerDecision
from cam_acq.recording.buffer import BayerRingBuffer, ring_capacity_frames
from cam_acq.recording.controller import RecordingController
from cam_acq.recording.grab import run_camera_grab_loop
from cam_acq.recording.gst_encode import encode_bayer_frames_to_mp4
from cam_acq.recording.storage import StorageManager


def codec_profile_schedule(
    buffer_sec: float,
    split_interval_sec: float,
) -> tuple[float, float]:
    """Derive grab duration and trigger offset from .env recording timing."""
    trigger_at_sec = buffer_sec
    duration_sec = buffer_sec + split_interval_sec + buffer_sec
    return duration_sec, trigger_at_sec


def _profile_ring_capacity(fps: float, buffer_sec: float, split_interval_sec: float) -> int:
    """Ring must cover pre + event + post; capped by what RAM can retain at full Bayer."""
    ring_sec = buffer_sec * 2 + split_interval_sec
    return ring_capacity_frames(fps, buffer_sec) if ring_sec > buffer_sec * 3 else max(
        1, int(fps * ring_sec) + 5
    )


def _safe_flush_chunk_sec(ring_retention_sec: float, buffer_sec: float) -> float:
    """Wall-clock span per incremental flush while the ring is still valid."""
    return max(1.0, ring_retention_sec - 2 * buffer_sec)


def _aggregate_codec_chunks(codec: str, chunks: list[dict[str, object]]) -> dict[str, object]:
    """Roll chunk encodes into per-segment and total stats for one codec."""
    by_seg: dict[int, list[dict[str, object]]] = {}
    for profile in chunks:
        seg_idx = int(profile.get("segment_index", 0))
        by_seg.setdefault(seg_idx, []).append(profile)

    segments: list[dict[str, object]] = []
    total_bytes = 0
    total_frames = 0
    total_encode_sec = 0.0
    peak_gpu = 0
    peak_enc = 0
    for seg_idx in sorted(by_seg):
        parts = by_seg[seg_idx]
        seg_bytes = sum(int(p["file_bytes"]) for p in parts)
        seg_frames = sum(int(p["frame_count"]) for p in parts)
        seg_encode = sum(float(p["encode_sec"]) for p in parts)
        if parts:
            peak_gpu = max(peak_gpu, max(int(p["gpu_peak_util_pct"]) for p in parts))
            peak_enc = max(peak_enc, max(int(p["encoder_peak_util_pct"]) for p in parts))
        segments.append(
            {
                "segment_index": seg_idx,
                "chunk_count": len(parts),
                "chunks": parts,
                "frame_count": seg_frames,
                "file_bytes": seg_bytes,
                "encode_sec": round(seg_encode, 3),
            }
        )
        total_bytes += seg_bytes
        total_frames += seg_frames
        total_encode_sec += seg_encode

    return {
        "codec": codec,
        "segment_count": len(segments),
        "segments": segments,
        "chunk_count": len(chunks),
        "frame_count": total_frames,
        "file_bytes": total_bytes,
        "encode_sec": round(total_encode_sec, 3),
        "encode_fps": round(total_frames / total_encode_sec, 2) if total_encode_sec > 0 else 0.0,
        "gpu_peak_util_pct": peak_gpu,
        "encoder_peak_util_pct": peak_enc,
    }


def _split_frame_segments(
    frames: list,
    *,
    win_start_us: int,
    win_end_us: int,
    split_interval_sec: float,
) -> list[tuple[int, list]]:
    """Mirror RecordingController segment boundaries for profile encodes."""
    split_us = int(split_interval_sec * 1_000_000)
    segments: list[tuple[int, list]] = []
    seg_idx = 0
    t = win_start_us
    while t < win_end_us:
        seg_end = min(t + split_us, win_end_us)
        seg_frames = [f for f in frames if t <= f.host_recv_us <= seg_end]
        if seg_frames:
            segments.append((seg_idx, seg_frames))
            seg_idx += 1
        t = seg_end
    return segments


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
    bayer_format: str,
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
        bayer_format=bayer_format,
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
        bayer_format=settings.bayer_format,
        codec=settings.encoding_codec,
        bitrate_bps=int(bitrate_mbps * 1_000_000),
        gpu_id=settings.gpu_id,
    )
    cap = _profile_ring_capacity(
        NOMINAL_FPS,
        settings.recording_buffer_sec,
        settings.recording_split_interval_sec,
    )
    controller._rings[camera_index] = BayerRingBuffer(cap)
    ring_retention_sec = cap / NOMINAL_FPS
    buf_us = int(settings.recording_buffer_sec * 1_000_000)
    split_us = int(settings.recording_split_interval_sec * 1_000_000)
    TimeSyncManager().begin_session(
        settings.cameras,
        timestamp_reset=settings.timestamp_reset_on_session,
    )

    stop_at = time.monotonic() + duration_sec
    trigger_at = time.monotonic() + trigger_at_sec
    errors: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bitrate_bps = int(bitrate_mbps * 1_000_000)
    safe_chunk_sec = _safe_flush_chunk_sec(ring_retention_sec, settings.recording_buffer_sec)
    chunk_us = int(safe_chunk_sec * 1_000_000)
    chunk_profiles: dict[str, list[dict[str, object]]] = {codec: [] for codec in codecs}
    flush_watermark_us: int | None = None
    chunk_seq = 0
    resolution: str | None = None

    def _encode_window_chunk(chunk_start_us: int, chunk_end_us: int) -> bool:
        nonlocal chunk_seq, resolution
        ring = controller._rings[camera_index]
        chunk_frames = ring.frames_in_host_window(chunk_start_us, chunk_end_us)
        if len(chunk_frames) < 2:
            return False
        win_start_us = decision.started_at_host_us - buf_us
        split_seg = int((chunk_start_us - win_start_us) // split_us) if split_us else 0
        for codec in codecs:
            out = (
                output_dir
                / f"{stamp}_cam{camera_index}_{codec}_{int(bitrate_mbps)}mbps"
                f"_seg{split_seg:02d}_c{chunk_seq:04d}.mp4"
            )
            profile = _encode_profile(
                chunk_frames,
                output_path=out,
                bayer_format=settings.bayer_format,
                fps=NOMINAL_FPS,
                codec=codec,
                bitrate_bps=bitrate_bps,
                gpu_id=settings.gpu_id,
            )
            profile["segment_index"] = split_seg
            profile["chunk_index"] = chunk_seq
            chunk_profiles[codec].append(profile)
        if resolution is None:
            resolution = f"{chunk_frames[0].width}x{chunk_frames[0].height}"
        chunk_seq += 1
        return True

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

    decision: TriggerDecision | None = None
    while time.monotonic() < stop_at:
        if decision is None and time.monotonic() >= trigger_at:
            started_us = int(time.monotonic() * 1_000_000)
            decision = TriggerDecision(
                trigger_type="human_detection",
                source="codec_profile",
                started_at_host_us=started_us,
                ended_at_host_us=started_us + split_us,
                manual=True,
                camera_indices=(camera_index,),
            )
            controller.schedule_trigger(decision)
            flush_watermark_us = decision.started_at_host_us - buf_us

        if decision is not None and flush_watermark_us is not None:
            now_us = int(time.monotonic() * 1_000_000)
            win_end_us = decision.ended_at_host_us + buf_us
            chunk_end_us = flush_watermark_us + chunk_us
            if chunk_end_us <= min(now_us, win_end_us):
                if _encode_window_chunk(flush_watermark_us, chunk_end_us):
                    flush_watermark_us = chunk_end_us
                else:
                    flush_watermark_us = chunk_end_us

        if controller.pending_ready():
            break
        time.sleep(0.05)

    thread.join(timeout=duration_sec + 30.0)

    if decision is None:
        print("no trigger fired", file=sys.stderr)
        return 1

    if flush_watermark_us is not None:
        win_end_us = decision.ended_at_host_us + buf_us
        if flush_watermark_us < win_end_us:
            _encode_window_chunk(flush_watermark_us, win_end_us)
    controller._pending = None

    if not any(chunk_profiles[c] for c in codecs):
        print("no encoded chunks captured", file=sys.stderr)
        return 1

    runs = [_aggregate_codec_chunks(codec, chunk_profiles[codec]) for codec in codecs]

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
        "split_interval_sec": settings.recording_split_interval_sec,
        "ring_capacity_frames": cap,
        "ring_retention_sec": round(ring_retention_sec, 2),
        "flush_chunk_sec": safe_chunk_sec,
        "incremental_flush": settings.recording_split_interval_sec > ring_retention_sec - (
            2 * settings.recording_buffer_sec
        ),
        "bitrate_mbps": bitrate_mbps,
        "resolution": resolution,
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
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="default: BUFFER + SPLIT_INTERVAL + BUFFER from .env",
    )
    parser.add_argument(
        "--trigger-at",
        type=float,
        default=None,
        help="default: RECORDING_BUFFER_SEC from .env",
    )
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
    settings = load_settings(args.env_file)
    default_duration, default_trigger = codec_profile_schedule(
        settings.recording_buffer_sec,
        settings.recording_split_interval_sec,
    )
    duration = default_duration if args.duration is None else args.duration
    trigger_at = default_trigger if args.trigger_at is None else args.trigger_at
    min_duration = (
        settings.recording_buffer_sec
        + settings.recording_split_interval_sec
        + settings.recording_buffer_sec
    )
    if duration < min_duration - 0.01:
        print(
            f"duration must be >= {min_duration}s "
            f"(buffer + split_interval + buffer from .env)",
            file=sys.stderr,
        )
        return 1
    if trigger_at < settings.recording_buffer_sec - 0.01:
        print("trigger-at must be >= RECORDING_BUFFER_SEC", file=sys.stderr)
        return 1
    bitrate = args.bitrate_mbps if args.bitrate_mbps is not None else settings.encoding_bitrate_mbps
    return run_codec_profile(
        camera_index=args.camera_index,
        duration_sec=duration,
        trigger_at_sec=trigger_at,
        codecs=tuple(args.codecs),
        bitrate_mbps=bitrate,
        env_file=args.env_file,
        output_dir=args.output_dir,
        output_json=args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
