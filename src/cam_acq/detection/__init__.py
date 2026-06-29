"""Human detection helpers (bbox transform, events, recording trigger)."""

from cam_acq.detection.bbox import (
    BBox,
    LetterboxParams,
    bbox_resized_to_original,
    clamp_bbox_to_frame,
    compute_letterbox,
    filter_person_detections,
)
from cam_acq.detection.events import (
    Detection,
    DetectionFrameEvent,
    RecordingTrigger,
    TriggerDecision,
)

__all__ = [
    "BBox",
    "LetterboxParams",
    "bbox_resized_to_original",
    "clamp_bbox_to_frame",
    "compute_letterbox",
    "filter_person_detections",
    "Detection",
    "DetectionFrameEvent",
    "RecordingTrigger",
    "TriggerDecision",
]
