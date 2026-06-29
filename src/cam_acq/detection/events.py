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


@dataclass(frozen=True)
class TriggerAction:
    """Side-effect for RecordingController from RecordingTrigger."""

    kind: str  # schedule | extend_end | finalize_end
    decision: TriggerDecision | None = None
    ended_at_host_us: int | None = None


# Open-ended manual session until manual_stop (pending_ready stays false).
_MANUAL_OPEN_END_US = 9_000_000_000_000_000


@dataclass
class RecordingTrigger:
    """Event + manual recording state.

    Manual: user start -> user stop (not tied to RECORDING_BUFFER_SEC duration).
    Event: starts on person detect; ends after buffer_sec with no person detected.
    Each new person detect resets the silence countdown to detect_time + buffer_sec.

    Manual has priority over event (event frames ignored while manual is active).
    """

    buffer_sec: float
    confidence_threshold: float
    camera_indices: tuple[int, ...]
    _window_start_host_us: int | None = field(default=None, init=False, repr=False)
    _last_person_us: int | None = field(default=None, init=False, repr=False)
    _manual_active: bool = field(default=False, init=False, repr=False)
    _event_session_open: bool = field(default=False, init=False, repr=False)

    def _buffer_us(self) -> int:
        return int(self.buffer_sec * 1_000_000)

    def on_frame(
        self,
        event: DetectionFrameEvent,
        host_recv_us: int | None = None,
    ) -> TriggerAction | None:
        """Process one detection frame; event recording only (manual uses start/stop)."""
        if not event.has_person:
            return None
        now_us = host_recv_us if host_recv_us is not None else event.host_recv_us
        if self._manual_active:
            return None
        return self._event_person_detected(now_us)

    def on_detection(
        self,
        event: DetectionFrameEvent,
        host_recv_us: int | None = None,
    ) -> TriggerDecision | None:
        """Legacy probe hook: returns decision only on new event session open."""
        action = self.on_frame(event, host_recv_us=host_recv_us)
        if action is None or action.kind != "schedule":
            return None
        return action.decision

    def _event_person_detected(self, now_us: int) -> TriggerAction:
        """Person seen: open session or extend silence deadline (now + buffer_sec)."""
        end_us = now_us + self._buffer_us()
        self._last_person_us = now_us
        if not self._event_session_open:
            self._event_session_open = True
            self._window_start_host_us = now_us
            decision = TriggerDecision(
                trigger_type="human_detection",
                source="auto",
                started_at_host_us=now_us,
                ended_at_host_us=end_us,
                manual=False,
                camera_indices=self.camera_indices,
            )
            return TriggerAction(kind="schedule", decision=decision)
        return TriggerAction(kind="extend_end", ended_at_host_us=end_us)

    def manual_start(self, host_us: int | None = None) -> TriggerAction:
        """Start manual recording until manual_stop; supersedes active event session."""
        now_us = int(time.monotonic() * 1_000_000) if host_us is None else host_us
        self._manual_active = True
        self._event_session_open = False
        self._last_person_us = None
        self._window_start_host_us = now_us
        decision = TriggerDecision(
            trigger_type="human_detection",
            source="manual",
            started_at_host_us=now_us,
            ended_at_host_us=now_us + _MANUAL_OPEN_END_US,
            manual=True,
            camera_indices=self.camera_indices,
        )
        return TriggerAction(kind="schedule", decision=decision)

    def manual_stop(self, host_us: int | None = None) -> TriggerAction:
        """End manual recording at host monotonic time."""
        if not self._manual_active:
            raise RuntimeError("manual recording not active")
        now_us = int(time.monotonic() * 1_000_000) if host_us is None else host_us
        self._manual_active = False
        return TriggerAction(kind="finalize_end", ended_at_host_us=now_us)

    def manual_trigger(self, host_us: int | None = None) -> TriggerDecision:
        """Alias for manual_start (returns decision for legacy callers)."""
        action = self.manual_start(host_us=host_us)
        assert action.decision is not None
        return action.decision

    def clear_session(self) -> None:
        """Reset after controller flush; allows a new event session."""
        if self._manual_active:
            return
        self._event_session_open = False
        self._window_start_host_us = None
        self._last_person_us = None

    @property
    def manual_active(self) -> bool:
        return self._manual_active

    @property
    def event_session_open(self) -> bool:
        return self._event_session_open and not self._manual_active

    @property
    def is_active(self) -> bool:
        """True while manual is on or event session is open (before flush)."""
        return self._manual_active or self._event_session_open
