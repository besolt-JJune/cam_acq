"""BBox coordinate transforms between detection input and camera resolution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BBox:
    """Axis-aligned box in pixel coordinates (inclusive min, exclusive max)."""

    x1: float
    y1: float
    x2: float
    y2: float

    def as_dict(self) -> dict[str, float]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    @classmethod
    def from_dict(cls, d: dict[str, float]) -> BBox:
        return cls(x1=d["x1"], y1=d["y1"], x2=d["x2"], y2=d["y2"])


@dataclass(frozen=True)
class LetterboxParams:
    """YOLO letterbox mapping from camera frame to network input."""

    scale: float
    pad_x: float
    pad_y: float
    input_w: int
    input_h: int
    camera_w: int
    camera_h: int


def compute_letterbox(
    camera_w: int,
    camera_h: int,
    input_w: int,
    input_h: int,
    *,
    symmetric_padding: bool = True,
) -> LetterboxParams:
    """Compute letterbox scale and padding (matches nvinfer maintain-aspect-ratio)."""
    if camera_w <= 0 or camera_h <= 0 or input_w <= 0 or input_h <= 0:
        raise ValueError("camera and input dimensions must be positive")

    scale = min(input_w / camera_w, input_h / camera_h)
    new_w = camera_w * scale
    new_h = camera_h * scale

    if symmetric_padding:
        pad_x = (input_w - new_w) / 2.0
        pad_y = (input_h - new_h) / 2.0
    else:
        pad_x = 0.0
        pad_y = input_h - new_h

    return LetterboxParams(
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
        input_w=input_w,
        input_h=input_h,
        camera_w=camera_w,
        camera_h=camera_h,
    )


def bbox_resized_to_original(bbox: BBox, letterbox: LetterboxParams) -> BBox:
    """Map detection-space bbox back to camera (4K) coordinates."""
    inv = 1.0 / letterbox.scale
    return BBox(
        x1=(bbox.x1 - letterbox.pad_x) * inv,
        y1=(bbox.y1 - letterbox.pad_y) * inv,
        x2=(bbox.x2 - letterbox.pad_x) * inv,
        y2=(bbox.y2 - letterbox.pad_y) * inv,
    )


def clamp_bbox_to_frame(bbox: BBox, width: int, height: int) -> BBox:
    """Clip bbox to [0, width] x [0, height]."""
    return BBox(
        x1=max(0.0, min(float(width), bbox.x1)),
        y1=max(0.0, min(float(height), bbox.y1)),
        x2=max(0.0, min(float(width), bbox.x2)),
        y2=max(0.0, min(float(height), bbox.y2)),
    )


PERSON_CLASS_ID = 0
PERSON_CLASS_NAME = "person"


@dataclass(frozen=True)
class RawDetection:
    """One nvinfer detection before coordinate transform."""

    class_id: int
    class_name: str
    confidence: float
    bbox: BBox


def mux_bbox_to_camera(
    bbox: BBox,
    resize_w: int,
    resize_h: int,
    camera_w: int,
    camera_h: int,
) -> BBox:
    """Map nvinfer bbox (mux / resize pixels) to full camera resolution."""
    if resize_w <= 0 or resize_h <= 0 or camera_w <= 0 or camera_h <= 0:
        return bbox
    sx = camera_w / resize_w
    sy = camera_h / resize_h
    return BBox(
        x1=bbox.x1 * sx,
        y1=bbox.y1 * sy,
        x2=bbox.x2 * sx,
        y2=bbox.y2 * sy,
    )


def filter_person_detections(
    detections: list[RawDetection],
    *,
    confidence_threshold: float,
    class_id: int = PERSON_CLASS_ID,
) -> list[RawDetection]:
    """Keep person class above confidence threshold."""
    return [
        d
        for d in detections
        if d.class_id == class_id and d.confidence >= confidence_threshold
    ]
