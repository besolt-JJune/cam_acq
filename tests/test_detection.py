"""BBox inverse transform self-check (no camera)."""

from cam_acq.detection.bbox import (
    BBox,
    compute_letterbox,
    bbox_resized_to_original,
    clamp_bbox_to_frame,
    filter_person_detections,
    RawDetection,
)
from cam_acq.detection.events import (
    DetectionFrameEvent,
    RecordingTrigger,
    build_detection_event,
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


if __name__ == "__main__":
  test_letterbox_4k_to_640()
  test_bbox_roundtrip_center()
  test_clamp_bbox()
  test_filter_person()
  test_build_detection_event()
  test_recording_trigger_opens_once()
  print("ok")
