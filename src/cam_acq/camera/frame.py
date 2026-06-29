"""Bayer RawImage → frame buffer for DeepStream appsrc."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from PIL import Image

from cam_acq.camera.bayer import resolve_gst_bayer_format


@dataclass(frozen=True)
class BayerFrame:
    """One copied Bayer payload for GPU debayer pipelines."""

    data: bytes
    width: int
    height: int
    gst_bayer_format: str


class DebayerBackend(str, Enum):
    """Where Bayer→RGB/NV12 runs. Phase 4 recording uses GPU_PHASE4."""

    CPU_SDK = "cpu_sdk"
    GPU_PHASE3 = "gpu_phase3"
    GPU_PHASE4 = "gpu_phase4"


def raw_image_to_rgb_resized(
    raw_image: Any,
    width: int,
    height: int,
) -> np.ndarray | None:
    """Convert gxipy RawImage (Bayer) to HxWx3 uint8 RGB at target size (CPU SDK)."""
    rgb = raw_image.convert("RGB")
    if rgb is None:
        return None
    arr = rgb.get_numpy_array()
    if arr is None:
        return None
    if arr.shape[1] == width and arr.shape[0] == height:
        return np.ascontiguousarray(arr, dtype=np.uint8)
    resized = Image.fromarray(arr, "RGB").resize((width, height), Image.Resampling.BILINEAR)
    return np.ascontiguousarray(resized, dtype=np.uint8)


def raw_image_to_bayer_frame(raw_image: Any, *, bayer_format: str) -> BayerFrame | None:
    """Copy RawImage Bayer bytes; GStreamer pattern from BAYER_FORMAT."""
    payload = raw_image.get_data()
    if payload is None:
        return None
    return BayerFrame(
        data=bytes(payload),
        width=int(raw_image.get_width()),
        height=int(raw_image.get_height()),
        gst_bayer_format=resolve_gst_bayer_format(bayer_format=bayer_format),
    )


def raw_image_to_frame(
    raw_image: Any,
    width: int,
    height: int,
    *,
    backend: DebayerBackend = DebayerBackend.CPU_SDK,
) -> np.ndarray | None:
    """Dispatch Bayer conversion by backend (GPU paths deferred; see 11_field_pending_work.md §6)."""
    if backend == DebayerBackend.CPU_SDK:
        return raw_image_to_rgb_resized(raw_image, width, height)
    if backend == DebayerBackend.GPU_PHASE3:
        raise NotImplementedError(
            "gpu_phase3 debayers inside DeepStreamYoloLive; use on_bayer_frame in grab loop"
        )
    if backend == DebayerBackend.GPU_PHASE4:
        raise NotImplementedError(
            "gpu_phase4 debayers in recording encode (gst_encode.bayer2rgb), not live RGB"
        )
    raise NotImplementedError(f"debayer backend {backend.value!r} is not implemented")


def parse_debayer_backend(value: str) -> DebayerBackend:
    """Parse DEBAYER_MODE env string."""
    try:
        return DebayerBackend(value.strip().lower())
    except ValueError as exc:
        allowed = ", ".join(b.value for b in DebayerBackend)
        raise ValueError(f"invalid DEBAYER_MODE {value!r}; expected one of: {allowed}") from exc
