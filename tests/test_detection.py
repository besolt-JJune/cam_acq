"""BBox inverse transform self-check (no camera)."""

import tempfile
from pathlib import Path

from cam_acq.detection.bbox import (
    BBox,
    compute_letterbox,
    bbox_resized_to_original,
    clamp_bbox_to_frame,
    filter_person_detections,
    mux_bbox_to_camera,
    RawDetection,
)
from cam_acq.detection.events import (
    DetectionFrameEvent,
    RecordingTrigger,
    build_detection_event,
    build_detection_event_from_mux,
)


def test_letterbox_4k_to_640():
  lb = compute_letterbox(3840, 2160, 640, 640)
  assert lb.scale == 640 / 3840
  assert abs(lb.pad_y - (640 - 2160 * lb.scale) / 2) < 0.01


def test_bbox_roundtrip_center():
  lb = compute_letterbox(3840, 2160, 640, 640)
  det = BBox(x1=300.0, y1=280.0, x2=340.0, y2=360.0)
  orig = bbox_resized_to_original(det, lb)
  assert 1400 < orig.x1 < 2000
  assert 800 < orig.y1 < 1200


def test_clamp_bbox():
  clipped = clamp_bbox_to_frame(BBox(-10, -5, 4000, 2200), 3840, 2160)
  assert clipped.x1 == 0
  assert clipped.y1 == 0
  assert clipped.x2 == 3840
  assert clipped.y2 == 2160


def test_filter_person():
  raw = [
    RawDetection(0, "person", 0.9, BBox(1, 2, 3, 4)),
    RawDetection(1, "car", 0.99, BBox(1, 2, 3, 4)),
    RawDetection(0, "person", 0.3, BBox(1, 2, 3, 4)),
  ]
  out = filter_person_detections(raw, confidence_threshold=0.5)
  assert len(out) == 1
  assert out[0].confidence == 0.9


def test_build_detection_event():
  lb = compute_letterbox(3840, 2160, 640, 640)
  raw = [RawDetection(0, "person", 0.91, BBox(100, 50, 150, 200))]
  ev = build_detection_event(
    camera_index=0,
    frame_id=42,
    timestamp_us=371100,
    host_recv_us=9_876_543_210,
    raw=raw,
    letterbox=lb,
    confidence_threshold=0.5,
  )
  assert isinstance(ev, DetectionFrameEvent)
  assert ev.has_person
  assert ev.detections[0].bbox_original.x1 >= 0


def test_mux_bbox_to_camera():
    bbox = BBox(100.0, 50.0, 200.0, 150.0)
    orig = mux_bbox_to_camera(bbox, 960, 540, 3840, 2160)
    assert orig.x1 == 400.0
    assert orig.y2 == 600.0


def test_build_detection_event_from_mux():
    raw = [RawDetection(0, "person", 0.88, BBox(96.0, 54.0, 192.0, 162.0))]
    ev = build_detection_event_from_mux(
        camera_index=1,
        frame_id=7,
        timestamp_us=1000,
        host_recv_us=2_000_000,
        raw=raw,
        resize_w=960,
        resize_h=540,
        camera_w=3840,
        camera_h=2160,
        confidence_threshold=0.5,
    )
    assert ev.has_person
    assert ev.camera_index == 1
    assert ev.detections[0].bbox_original.x2 == 768.0


def test_recording_trigger_opens_once():
  import time

  trig = RecordingTrigger(
    buffer_sec=10.0,
    confidence_threshold=0.5,
    camera_indices=(0, 1),
  )
  lb = compute_letterbox(3840, 2160, 640, 640)
  raw = [RawDetection(0, "person", 0.9, BBox(10, 10, 20, 30))]
  t0 = int(time.monotonic() * 1_000_000)
  ev = build_detection_event(
    camera_index=0,
    frame_id=1,
    timestamp_us=0,
    host_recv_us=t0,
    raw=raw,
    letterbox=lb,
    confidence_threshold=0.5,
  )
  d1 = trig.on_detection(ev)
  d2 = trig.on_detection(ev, host_recv_us=t0 + 500_000)
  assert d1 is not None
  assert d2 is None
  assert trig.is_active


def test_bridge_recording_hooks():
  """Probe path: note_detection + apply_trigger_action on RecordingController."""
  from cam_acq.detection.gst_meta import LiveDetectionBridge

  class _FakeRec:
    def __init__(self) -> None:
      self.detections: list[DetectionFrameEvent] = []
      self.actions: list = []

    def note_detection(self, event: DetectionFrameEvent) -> None:
      self.detections.append(event)

    def apply_trigger_action(self, action) -> None:
      self.actions.append(action)

  rec = _FakeRec()
  trig = RecordingTrigger(buffer_sec=10.0, confidence_threshold=0.5, camera_indices=(0,))
  bridge = LiveDetectionBridge(
    resize_w=640,
    resize_h=640,
    camera_w=3840,
    camera_h=2160,
    confidence_threshold=0.5,
    trigger=trig,
    recording=rec,
  )
  lb = compute_letterbox(3840, 2160, 640, 640)
  ev = build_detection_event(
    camera_index=0,
    frame_id=1,
    timestamp_us=0,
    host_recv_us=1_000_000,
    raw=[RawDetection(0, "person", 0.9, BBox(10, 10, 20, 30))],
    letterbox=lb,
    confidence_threshold=0.5,
  )
  action = trig.on_frame(ev, host_recv_us=ev.host_recv_us)
  assert action is not None and action.kind == "schedule"
  rec.note_detection(ev)
  rec.apply_trigger_action(action)
  assert len(rec.detections) == 1
  assert len(rec.actions) == 1


def _person_event(host_us: int) -> DetectionFrameEvent:
  lb = compute_letterbox(3840, 2160, 640, 640)
  return build_detection_event(
    camera_index=0,
    frame_id=1,
    timestamp_us=0,
    host_recv_us=host_us,
    raw=[RawDetection(0, "person", 0.9, BBox(10, 10, 20, 30))],
    letterbox=lb,
    confidence_threshold=0.5,
  )


def _make_ctrl(buffer_sec: float = 5.0):
  from cam_acq.recording.controller import RecordingController
  from cam_acq.recording.storage import StorageManager

  storage = StorageManager(Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / "sub")
  return RecordingController(
    storage=storage,
    camera_indices=(0,),
    buffer_sec=buffer_sec,
    split_interval_sec=60.0,
    pixel_format="BayerRG8",
    bayer_format="rggb",
    codec="H265",
    bitrate_bps=8_000_000,
    gpu_id=0,
  )


def test_event_case1_silence_ends_after_buffer():
  """person detect -> no detect -> buffer_sec later ready to flush."""
  trig = RecordingTrigger(buffer_sec=5.0, confidence_threshold=0.5, camera_indices=(0,))
  ctrl = _make_ctrl(5.0)
  ev = _person_event(0)
  ctrl.apply_trigger_action(trig.on_frame(ev, host_recv_us=0))
  assert ctrl._pending.ended_at_host_us == 5_000_000
  assert not ctrl.pending_ready(now_host_us=4_999_999)
  assert ctrl.pending_ready(now_host_us=5_000_000)


def test_event_case2_redetect_resets_silence():
  """Silence countdown resets when person detected again during post tail."""
  trig = RecordingTrigger(buffer_sec=5.0, confidence_threshold=0.5, camera_indices=(0,))
  ctrl = _make_ctrl(5.0)
  ev = _person_event(0)
  ctrl.apply_trigger_action(trig.on_frame(ev, host_recv_us=0))
  assert ctrl._pending.ended_at_host_us == 5_000_000
  ctrl.apply_trigger_action(trig.on_frame(ev, host_recv_us=3_000_000))
  assert ctrl._pending.ended_at_host_us == 8_000_000
  assert not ctrl.pending_ready(now_host_us=7_999_999)
  assert ctrl.pending_ready(now_host_us=8_000_000)


def test_manual_start_stop_open_until_stop():
  import time

  trig = RecordingTrigger(buffer_sec=5.0, confidence_threshold=0.5, camera_indices=(0,))
  ctrl = _make_ctrl(5.0)
  t0 = int(time.monotonic() * 1_000_000)
  ctrl.apply_trigger_action(trig.manual_start(host_us=t0))
  assert trig.manual_active
  assert not ctrl.pending_ready(now_host_us=t0 + 1_000_000)
  ctrl.apply_trigger_action(trig.manual_stop(host_us=t0 + 2_000_000))
  assert not trig.manual_active
  assert ctrl._pending.ended_at_host_us == t0 + 2_000_000
  assert ctrl.pending_ready(now_host_us=t0 + 2_000_000)


def test_manual_priority_case2_event_ignored_during_manual():
  """Case 2: manual active -> event -> events do not extend or reopen window."""
  import time

  trig = RecordingTrigger(buffer_sec=10.0, confidence_threshold=0.5, camera_indices=(0, 1))
  lb = compute_letterbox(3840, 2160, 640, 640)
  raw = [RawDetection(0, "person", 0.9, BBox(10, 10, 20, 30))]
  t0 = int(time.monotonic() * 1_000_000)
  ev = build_detection_event(
    camera_index=0,
    frame_id=1,
    timestamp_us=0,
    host_recv_us=t0,
    raw=raw,
    letterbox=lb,
    confidence_threshold=0.5,
  )
  manual = trig.manual_start(host_us=t0).decision
  assert manual.manual
  assert trig.manual_active
  during = trig.on_detection(ev, host_recv_us=t0 + 2_000_000)
  assert during is None
  assert trig.manual_active


def test_manual_priority_case3_overrides_event():
  """Case 3: event active -> manual start -> manual window replaces event."""
  import time

  trig = RecordingTrigger(buffer_sec=10.0, confidence_threshold=0.5, camera_indices=(0, 1))
  lb = compute_letterbox(3840, 2160, 640, 640)
  raw = [RawDetection(0, "person", 0.9, BBox(10, 10, 20, 30))]
  t0 = int(time.monotonic() * 1_000_000)
  ev = build_detection_event(
    camera_index=0,
    frame_id=1,
    timestamp_us=0,
    host_recv_us=t0,
    raw=raw,
    letterbox=lb,
    confidence_threshold=0.5,
  )
  auto = trig.on_detection(ev, host_recv_us=t0)
  assert auto is not None
  assert not trig.manual_active
  manual = trig.manual_start(host_us=t0 + 5_000_000).decision
  assert manual.manual
  assert manual.started_at_host_us == t0 + 5_000_000
  assert trig.manual_active
  assert trig.on_detection(ev, host_recv_us=t0 + 6_000_000) is None


def test_controller_manual_overrides_event_open_segment():
  """Event NVENC open → manual start must not push to a finalized encoder."""
  import time
  from datetime import datetime, timezone
  from unittest.mock import MagicMock, patch

  from cam_acq.camera.timesync import CameraTimeAnchor, SessionTimeSync
  from cam_acq.detection.events import TriggerAction, TriggerDecision
  from cam_acq.recording.buffer import BufferedFrame
  from cam_acq.recording.controller import RecordingController, _OpenSegmentEncode
  from cam_acq.recording.storage import StorageManager

  with tempfile.TemporaryDirectory() as tmp:
    storage = StorageManager(Path(tmp), Path(tmp) / "sub")
    ctrl = RecordingController(
      storage=storage,
      camera_indices=(0,),
      buffer_sec=2.0,
      split_interval_sec=300.0,
      pixel_format="BayerRG8",
      bayer_format="rggb",
      codec="H265",
      bitrate_bps=8_000_000,
      gpu_id=0,
    )
    t0 = int(time.monotonic() * 1_000_000)
    event = TriggerDecision(
      trigger_type="human_detection",
      source="auto",
      started_at_host_us=t0,
      ended_at_host_us=t0 + 20_000_000,
      manual=False,
      camera_indices=(0,),
    )
    ctrl.apply_trigger_action(TriggerAction(kind="schedule", decision=event))
    enc = MagicMock()
    enc.push_frames = MagicMock(return_value=1)
    frame = BufferedFrame(
      frame_id=1,
      timestamp_tick=1000,
      host_recv_us=t0 + 1_000_000,
      width=100,
      height=80,
      data=b"\x00" * 8000,
    )
    paths = storage.segment_paths(
      storage.make_basename(camera_index=0, segment_index=0, when=time.time())
    )
    open_seg = _OpenSegmentEncode(
      camera_index=0,
      segment_index=0,
      seg_start_us=t0,
      seg_end_us=t0 + 300_000_000,
      encoder=enc,
      video_path=paths["video"],
      session_path=paths["session"],
      frames_path=paths["frames"],
      frames_file=paths["frames"].open("w", encoding="utf-8"),
      width=100,
      height=80,
    )
    ctrl._open_segments[0] = open_seg
    ctrl._session_anchor_us = t0 - 2_000_000
    ctrl._time_sync = SessionTimeSync(
      strategy="host_clock_sync",
      host_t0_monotonic=time.monotonic(),
      host_t0_wall=datetime.now(timezone.utc).isoformat(),
      timestamp_reset_on_session=False,
      cross_camera_skew_tolerance_ms=50,
      anchors=(
        CameraTimeAnchor(
          camera_index=0,
          ip="10.0.0.1",
          camera_ts0=0,
          tick_frequency_hz=1_000_000_000,
          reset_performed=False,
        ),
      ),
    )
    manual = TriggerDecision(
      trigger_type="human_detection",
      source="manual",
      started_at_host_us=t0 + 5_000_000,
      ended_at_host_us=t0 + 9_000_000_000_000_000,
      manual=True,
      camera_indices=(0,),
    )
    with patch.object(ctrl, "_finalize_open_segment") as fin:
      ctrl.apply_trigger_action(TriggerAction(kind="schedule", decision=manual))
      fin.assert_called_once()
    assert ctrl._pending is manual
    assert 0 not in ctrl._open_segments
    ctrl._push_frame_to_open_segment(open_seg, frame, tick_frequency_hz=1_000_000_000)
    enc.push_frames.assert_not_called()


def test_controller_auto_cannot_override_manual_pending():
  from cam_acq.detection.events import TriggerDecision
  from cam_acq.recording.controller import RecordingController
  from cam_acq.recording.storage import StorageManager

  with tempfile.TemporaryDirectory() as tmp:
    storage = StorageManager(Path(tmp), Path(tmp) / "sub")
    ctrl = RecordingController(
      storage=storage,
      camera_indices=(0,),
      buffer_sec=5.0,
      split_interval_sec=60.0,
      pixel_format="BayerRG8",
      bayer_format="rggb",
      codec="H265",
      bitrate_bps=8_000_000,
      gpu_id=0,
    )
    manual = TriggerDecision(
      trigger_type="human_detection",
      source="manual",
      started_at_host_us=1_000_000,
      ended_at_host_us=11_000_000,
      manual=True,
      camera_indices=(0,),
    )
    auto = TriggerDecision(
      trigger_type="human_detection",
      source="auto",
      started_at_host_us=2_000_000,
      ended_at_host_us=12_000_000,
      manual=False,
      camera_indices=(0,),
    )
    ctrl.schedule_trigger(manual)
    ctrl.schedule_trigger(auto)
    assert ctrl._pending is manual
    ctrl.schedule_trigger(
      TriggerDecision(
        trigger_type="human_detection",
        source="manual",
        started_at_host_us=3_000_000,
        ended_at_host_us=13_000_000,
        manual=True,
        camera_indices=(0,),
      )
    )
    assert ctrl._pending.started_at_host_us == 3_000_000


if __name__ == "__main__":
  test_letterbox_4k_to_640()
  test_bbox_roundtrip_center()
  test_clamp_bbox()
  test_filter_person()
  test_build_detection_event()
  test_mux_bbox_to_camera()
  test_build_detection_event_from_mux()
  test_recording_trigger_opens_once()
  test_bridge_recording_hooks()
  test_event_case1_silence_ends_after_buffer()
  test_event_case2_redetect_resets_silence()
  test_manual_start_stop_open_until_stop()
  test_manual_priority_case2_event_ignored_during_manual()
  test_manual_priority_case3_overrides_event()
  test_controller_manual_overrides_event_open_segment()
  test_controller_auto_cannot_override_manual_pending()
  print("ok")
