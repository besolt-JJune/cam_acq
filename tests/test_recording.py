"""Recording ring buffer and storage self-check (no camera/GPU)."""

import tempfile
from pathlib import Path

from cam_acq.recording.buffer import BayerRingBuffer, BufferedFrame, ring_capacity_frames
from cam_acq.recording.storage import StorageManager


def test_ring_window():
    buf = BayerRingBuffer(5)
    for i in range(7):
        buf.push(
            BufferedFrame(
                frame_id=i,
                timestamp_tick=i * 1000,
                host_recv_us=i * 1_000_000,
                width=4,
                height=2,
                data=bytes([i]),
            )
        )
    win = buf.frames_in_host_window(2_000_000, 5_999_999)
    assert [f.frame_id for f in win] == [2, 3, 4, 5]


def test_ring_capacity_formula():
    assert ring_capacity_frames(23.0, 10.0) >= 690


def test_storage_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        primary = Path(tmp) / "blocked_file"
        primary.write_text("x", encoding="utf-8")
        fallback = Path(tmp) / "ok"
        sm = StorageManager(primary, fallback)
        assert sm.location.is_fallback
        assert sm.location.path == fallback


def test_basename_same_timestamp_across_cameras():
    """All channels in one segment share the same wall-clock prefix."""
    with tempfile.TemporaryDirectory() as tmp:
        sm = StorageManager(Path(tmp) / "primary", Path(tmp) / "sub")
        when = 1_719_600_000.0
        b0 = sm.make_basename(camera_index=0, segment_index=0, when=when)
        b1 = sm.make_basename(camera_index=1, segment_index=0, when=when)
        assert b0.partition("_cam")[0] == b1.partition("_cam")[0]
        assert b0.endswith("_cam0_seg00")
        assert b1.endswith("_cam1_seg00")
        manual = sm.make_basename(camera_index=0, segment_index=0, when=when, manual=True)
        assert manual.endswith("_cam0_seg00_manual")


def test_storage_fifo_cleanup_api():
    """RecordingController.flush_pending calls maybe_fifo_cleanup before encode."""
    with tempfile.TemporaryDirectory() as tmp:
        sm = StorageManager(Path(tmp) / "primary", Path(tmp) / "sub")
        assert callable(getattr(sm, "maybe_fifo_cleanup", None))
        assert sm.maybe_fifo_cleanup() == 0


def test_take_pending_window_frames():
    """Codec profile drains pending window without NVENC encode."""
    from cam_acq.detection.events import TriggerDecision
    from cam_acq.recording.buffer import BufferedFrame
    from cam_acq.recording.controller import RecordingController

    with tempfile.TemporaryDirectory() as tmp:
        sm = StorageManager(Path(tmp) / "primary", Path(tmp) / "sub")
        ctrl = RecordingController(
            storage=sm,
            camera_indices=(0,),
            buffer_sec=2.0,
            split_interval_sec=60.0,
            pixel_format="BayerRG8",
            bayer_format="RGGB",
            codec="H264",
            bitrate_bps=8_000_000,
            gpu_id=0,
            fps=10.0,
        )
        ring = ctrl._rings[0]
        for i in range(5):
            ring.push(
                BufferedFrame(
                    frame_id=i,
                    timestamp_tick=i * 1000,
                    host_recv_us=i * 1_000_000,
                    width=4,
                    height=2,
                    data=bytes(8),
                )
            )
        decision = TriggerDecision(
            trigger_type="human_detection",
            source="manual",
            started_at_host_us=2_000_000,
            ended_at_host_us=3_000_000,
            manual=True,
            camera_indices=(0,),
        )
        ctrl.schedule_trigger(decision)
        taken = ctrl.take_pending_window_frames()
        assert taken is not None
        got_decision, frames = taken
        assert got_decision.source == "manual"
        assert len(frames[0]) >= 1
        assert ctrl.take_pending_window_frames() is None


def test_codec_profile_schedule():
    from cam_acq.tools.codec_profile import codec_profile_schedule

    assert codec_profile_schedule(5.0, 360.0) == (370.0, 5.0)


def test_memory_profile_schedule():
    from cam_acq.tools.memory_profile import memory_profile_schedule

    assert memory_profile_schedule(5.0) == (40.0, 20.0)


def test_peak_summary():
    from cam_acq.tools.memory_profile import _peak_summary

    peaks = _peak_summary(
        [
            {"ram_used_bytes": 1_000, "ram_percent": 40.0, "vram_used_mb": 500},
            {"ram_used_bytes": 2_000, "ram_percent": 55.0, "vram_used_mb": 800},
        ]
    )
    assert peaks["ram_used_bytes_peak"] == 2_000
    assert peaks["vram_used_mb_peak"] == 800


def test_encode_bayer_mp4_optional():
    """GPU encode smoke test; skipped unless GST_ENCODE_TEST=1."""
    import os

    if os.getenv("GST_ENCODE_TEST") != "1":
        return
    from cam_acq.detection.gst_live import DeepStreamYoloLive  # noqa: F401 — gi before gxipy
    from cam_acq.recording.gst_encode import encode_bayer_frames_to_mp4

    w, h = 3840, 2160
    frames = [
        BufferedFrame(
            frame_id=i,
            timestamp_tick=i * 1000,
            host_recv_us=i * 1_000_000,
            width=w,
            height=h,
            data=bytes(w * h),
        )
        for i in range(3)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mp4"
        encode_bayer_frames_to_mp4(
            frames,
            output_path=out,
            bayer_format="RGGB",
            fps=23.0,
            codec="H264",
            bitrate_bps=4_000_000,
            gpu_id=0,
        )
        assert out.stat().st_size > 1000


if __name__ == "__main__":
    test_ring_window()
    test_ring_capacity_formula()
    test_storage_fallback()
    test_basename_same_timestamp_across_cameras()
    test_storage_fifo_cleanup_api()
    test_take_pending_window_frames()
    test_codec_profile_schedule()
    test_memory_profile_schedule()
    test_peak_summary()
    test_encode_bayer_mp4_optional()
    print("ok")
