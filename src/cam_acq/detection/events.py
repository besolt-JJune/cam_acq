"""Detection frame events and all-channel recording trigger state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from cam_acq.detection.bbox import (
    PERSON_CLASS_NAME,
    BBox,
    LetterboxParams,
    RawDetection,
    bbox_resized_to_original,
    clamp_bbox_to_frame,
    filter_person_detections,
    mux_bbox_to_camera,
)


@dataclass(frozen=True)
class Detection:
    """One person detection with resized and original bboxes."""

    class_name: str
    confidence: float
    bbox_resized: BBox
    bbox_original: BBox
    class_id: int = 0

    def as_frame_dict(self) -> dict:
        return {
            "class": self.class_name,
            "confidence": round(self.confidence, 4),
            "bbox_resized": self.bbox_resized.as_dict(),
            "bbox_original": self.bbox_original.as_dict(),
        }


@dataclass(frozen=True)
class DetectionFrameEvent:
    """Detections for one camera frame (feeds metadata and trigger)."""

    camera_index: int
    frame_id: int
    timestamp_us: int
    host_recv_us: int
    detections: tuple[Detection, ...]

    @property
    def has_person(self) -> bool:
        return len(self.detections) > 0


def build_detection_event_from_mux(
    *,
    camera_index: int,
    frame_id: int,
    timestamp_us: int,
    host_recv_us: int | None,
    raw: list[RawDetection],
    resize_w: int,
    resize_h: int,
    camera_w: int,
    camera_h: int,
    confidence_threshold: float,
) -> DetectionFrameEvent:
    """Build event from nvinfer rects in mux (resize) coordinates."""
    persons = filter_person_detections(raw, confidence_threshold=confidence_threshold)
    mapped: list[Detection] = []
    for d in persons:
        orig = clamp_bbox_to_frame(
            mux_bbox_to_camera(d.bbox, resize_w, resize_h, camera_w, camera_h),
            camera_w,
            camera_h,
        )
        mapped.append(
            Detection(
                class_id=d.class_id,
                class_name=d.class_name or PERSON_CLASS_NAME,
                confidence=d.confidence,
                bbox_resized=d.bbox,
                bbox_original=orig,
            )
        )
    recv = host_recv_us if host_recv_us is not None else int(time.monotonic() * 1_000_000)
    return DetectionFrameEvent(
        camera_index=camera_index,
        frame_id=frame_id,
        timestamp_us=timestamp_us,
        host_recv_us=recv,
        detections=tuple(mapped),
    )


def build_detection_event(
    *,
    camera_index: int,
    frame_id: int,
    timestamp_us: int,
    host_recv_us: int | None,
    raw: list[RawDetection],
    letterbox: LetterboxParams,
    confidence_threshold: float,
) -> DetectionFrameEvent:
    """Filter person detections and map bboxes to camera coordinates."""
    persons = filter_person_detections(raw, confidence_threshold=confidence_threshold)
    mapped: list[Detection] = []
    for d in persons:
        orig = clamp_bbox_to_frame(
            bbox_resized_to_original(d.bbox, letterbox),
            letterbox.camera_w,
            letterbox.camera_h,
        )
        mapped.append(
            Detection(
                class_id=d.class_id,
                class_name=d.class_name or PERSON_CLASS_NAME,
                confidence=d.confidence,
                bbox_resized=d.bbox,
                bbox_original=orig,
            )
        )
    recv = host_recv_us if host_recv_us is not None else int(time.monotonic() * 1_000_000)
    return DetectionFrameEvent(
        camera_index=camera_index,
        frame_id=frame_id,
        timestamp_us=timestamp_us,
        host_recv_us=recv,
        detections=tuple(mapped),
    )


@dataclass(frozen=True)
class TriggerDecision:
    """Recording window decision emitted to RecordingController (Phase 4)."""

    trigger_type: str
    source: str
    started_at_host_us: int
    ended_at_host_us: int
    manual: bool = False
    camera_indices: tuple[int, ...] = (0, 1)

    def as_dict(self) -> dict:
        return {
            "type": self.trigger_type,
            "source": self.source,
            "manual": self.manual,
            "started_at_host_us": self.started_at_host_us,
            "ended_at_host_us": self.ended_at_host_us,
            "camera_indices": list(self.camera_indices),
        }


@dataclass
class RecordingTrigger:
    """Extend recording while person is detected; all channels trigger together."""

    buffer_sec: float
    confidence_threshold: float
    camera_indices: tuple[int, ...]
    _active_until_host_us: int | None = field(default=None, init=False, repr=False)
    _window_start_host_us: int | None = field(default=None, init=False, repr=False)

    def on_detection(self, event: DetectionFrameEvent, host_recv_us: int | None = None) -> TriggerDecision | None:
        """Update trigger window; return decision when a new window opens."""
        if not event.has_person:
            return None

        now_us = host_recv_us if host_recv_us is not None else event.host_recv_us
        extend_to = now_us + int(self.buffer_sec * 1_000_000)

        if self._active_until_host_us is not None and now_us <= self._active_until_host_us:
            self._active_until_host_us = max(self._active_until_host_us, extend_to)
            return None

        self._window_start_host_us = now_us
        self._active_until_host_us = extend_to
        return TriggerDecision(
            trigger_type="human_detection",
            source="auto",
            started_at_host_us=now_us,
            ended_at_host_us=extend_to,
            manual=False,
            camera_indices=self.camera_indices,
        )

    def manual_trigger(self, host_us: int | None = None) -> TriggerDecision:
        """Start a manual all-channel recording window."""
        now_us = int(time.monotonic() * 1_000_000) if host_us is None else host_us
        end_us = now_us + int(self.buffer_sec * 1_000_000)
        self._window_start_host_us = now_us
        self._active_until_host_us = end_us
        return TriggerDecision(
            trigger_type="human_detection",
            source="manual",
            started_at_host_us=now_us,
            ended_at_host_us=end_us,
            manual=True,
            camera_indices=self.camera_indices,
        )

    @property
    def is_active(self) -> bool:
        if self._active_until_host_us is None:
            return False
        return int(time.monotonic() * 1_000_000) <= self._active_until_host_us
