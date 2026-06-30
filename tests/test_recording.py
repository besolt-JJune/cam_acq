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
        assert b0.endswith("_cam0_seg0000")
        assert b1.endswith("_cam1_seg0000")
        manual = sm.make_basename(camera_index=0, segment_index=0, when=when, manual=True)
        assert manual.endswith("_cam0_seg0000_manual")


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


def test_manual_record_stop_at_sec():
    """Default stop leaves encode margin; explicit override is honored."""
    from cam_acq.tools.deepstream_yolo_live import manual_record_stop_at_sec

    assert manual_record_stop_at_sec(duration_sec=60.0, explicit=None) == 55.0
    assert manual_record_stop_at_sec(duration_sec=10.0, explicit=None) == 5.0
    assert manual_record_stop_at_sec(duration_sec=60.0, explicit=40.0) == 40.0


def test_split_segments_in_host_window():
    """Segment indices follow RECORDING_SPLIT_INTERVAL_SEC from session anchor."""
    from cam_acq.recording.buffer import split_segments_in_host_window

    anchor = 1_000_000
    split = 60.0
    segs = split_segments_in_host_window(
        anchor_us=anchor,
        range_start_us=anchor + 50_000_000,
        range_end_us=anchor + 130_000_000,
        split_interval_sec=split,
    )
    assert segs == [
        (0, anchor + 50_000_000, anchor + 60_000_000),
        (1, anchor + 60_000_000, anchor + 120_000_000),
        (2, anchor + 120_000_000, anchor + 130_000_000),
    ]


def test_incremental_flush_chunk_sec():
    """Long split uses small ring + chunk flush (buffer=2, split=300)."""
    from cam_acq.recording.buffer import incremental_flush_chunk_sec, recording_ring_capacity_frames

    cap = recording_ring_capacity_frames(23.0, 2.0, 300.0)
    assert cap == ring_capacity_frames(23.0, 2.0)
    chunk = incremental_flush_chunk_sec(23.0, 2.0, 300.0)
    assert 1.0 <= chunk <= cap / 23.0


def test_ring_overflow_counted():
    """When ring is full, push evicts oldest and increments overflow_drops."""
    buf = BayerRingBuffer(3)
    for i in range(5):
        buf.push(
            BufferedFrame(
                frame_id=i,
                timestamp_tick=i,
                host_recv_us=i * 1_000_000,
                width=2,
                height=2,
                data=bytes([i]),
            )
        )
    assert buf.push_total == 5
    assert buf.overflow_drops == 2
    assert [f.frame_id for f in buf.frames_in_host_window(0, 10_000_000)] == [2, 3, 4]


def test_segment_index_at():
    """Split index follows anchor + RECORDING_SPLIT_INTERVAL_SEC."""
    from cam_acq.recording.buffer import segment_bounds_us, segment_index_at

    anchor = 1_000_000
    assert segment_index_at(anchor, anchor + 50_000_000, 60.0) == 0
    assert segment_index_at(anchor, anchor + 60_000_000, 60.0) == 1
    assert segment_bounds_us(anchor, 1, 60.0) == (anchor + 60_000_000, anchor + 120_000_000)


def test_ring_clear():
    buf = BayerRingBuffer(5)
    for i in range(3):
        buf.push(
            BufferedFrame(
                frame_id=i,
                timestamp_tick=i,
                host_recv_us=i * 1_000_000,
                width=2,
                height=2,
                data=bytes([i]),
            )
        )
    assert len(buf) == 3
    buf.clear()
    assert len(buf) == 0
    assert buf.oldest_host_recv_us() is None


def test_gige_offline_clears_ring_and_blocks_push():
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
        ring.push(
            BufferedFrame(
                frame_id=0,
                timestamp_tick=0,
                host_recv_us=1_000_000,
                width=4,
                height=2,
                data=bytes(8),
            )
        )
        ctrl.on_camera_offline(0, at_host_us=2_000_000, offline_event_index=1)
        assert len(ring) == 0
        assert ctrl._camera_offline[0] is True
        assert not ctrl.push_raw(0, _fake_raw())


def test_gige_reconnect_prebuffer_floor():
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
        ring.push(
            BufferedFrame(
                frame_id=0,
                timestamp_tick=0,
                host_recv_us=1_000_000,
                width=4,
                height=2,
                data=bytes(8),
            )
        )
        ctrl.on_camera_offline(0, at_host_us=2_000_000, offline_event_index=1)
        ctrl.on_camera_reconnect(0, at_host_us=5_000_000)
        assert ctrl._camera_offline[0] is False
        assert ctrl._prebuffer_floor_us[0] == 5_000_000
        assert len(ring) == 0
        taken = ring.frames_in_host_window(0, 10_000_000)
        assert all(f.host_recv_us >= 5_000_000 for f in taken) or not taken


def test_session_json_gige_disconnect_split():
    import json

    from cam_acq.detection.events import TriggerDecision
    from cam_acq.recording.metadata import write_session_json

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "session.json"
        decision = TriggerDecision(
            trigger_type="human_detection",
            source="yolo",
            started_at_host_us=1_000_000,
            ended_at_host_us=10_000_000,
            manual=False,
            camera_indices=(0,),
        )
        write_session_json(
            path,
            camera_index=0,
            segment_index=0,
            video_file="v.mp4",
            frames_file="f.jsonl",
            codec="H264",
            width=100,
            height=100,
            trigger=decision,
            buffer_sec=10.0,
            split_interval_sec=60.0,
            segment_start_host_us=1_000_000,
            segment_end_host_us=61_000_000,
            storage_path=str(tmp),
            storage_fallback=False,
            time_sync={"strategy": "host"},
            split_reason="gige_disconnect",
            split_at_host_us=5_000_000,
            offline_event_index=1,
        )
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["split"]["reason"] == "gige_disconnect"
        assert doc["split"]["at_host_us"] == 5_000_000
        assert doc["split"]["offline_event_index"] == 1


class _FakeRaw:
    def get_status(self):
        from gxipy.gxidef import GxFrameStatusList

        return GxFrameStatusList.SUCCESS

    def get_frame_id(self):
        return 1

    def get_timestamp(self):
        return 1000

    def get_width(self):
        return 4

    def get_height(self):
        return 2

    def get_data(self):
        return bytes(8)


def _fake_raw():
    return _FakeRaw()


if __name__ == "__main__":
    test_ring_window()
    test_ring_clear()
    test_gige_offline_clears_ring_and_blocks_push()
    test_gige_reconnect_prebuffer_floor()
    test_session_json_gige_disconnect_split()
    test_ring_overflow_counted()
    test_ring_capacity_formula()
    test_storage_fallback()
    test_basename_same_timestamp_across_cameras()
    test_storage_fifo_cleanup_api()
    test_take_pending_window_frames()
    test_codec_profile_schedule()
    test_memory_profile_schedule()
    test_peak_summary()
    test_encode_bayer_mp4_optional()
    test_manual_record_stop_at_sec()
    test_split_segments_in_host_window()
    test_incremental_flush_chunk_sec()
    test_segment_index_at()
    print("ok")
