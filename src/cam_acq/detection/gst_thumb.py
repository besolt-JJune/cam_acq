"""Pad probe: tap resized RGB from YOLO input chain for monitoring thumbnails."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import numpy as np

gi = __import__("gi")
gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

logger = logging.getLogger(__name__)
_warned_formats: set[str] = set()


def _caps_video_fields(caps: Gst.Caps) -> tuple[int, int, str, int] | None:
    """Return width, height, format string, and row stride in bytes."""
    structure = caps.get_structure(0)
    if structure is None:
        return None
    if not structure.get_name().startswith("video/"):
        return None
    ok_w, width = structure.get_int("width")
    ok_h, height = structure.get_int("height")
    fmt = structure.get_string("format")
    if not ok_w or not ok_h or fmt is None:
        return None
    stride = width
    if fmt in ("RGB", "BGR"):
        stride = width * 3
    elif fmt in ("RGBA", "RGBx", "BGRA", "BGRx"):
        stride = width * 4
    ok_stride, stride_val = structure.get_int("stride")
    if ok_stride and stride_val > 0:
        stride = stride_val
    return int(width), int(height), fmt, int(stride)


def _guess_fields_from_size(
    size: int, *, width: int, height: int
) -> tuple[int, int, str, int] | None:
    """Infer format when pad caps are not negotiated yet."""
    if width <= 0 or height <= 0:
        return None
    for fmt, bpp in (("BGRx", 4), ("RGBx", 4), ("RGBA", 4), ("BGR", 3), ("RGB", 3)):
        if size == width * height * bpp:
            return width, height, fmt, width * bpp
    return None


def gst_buffer_to_rgb(
    buf: Gst.Buffer,
    caps: Gst.Caps | None,
    *,
    width: int = 0,
    height: int = 0,
) -> np.ndarray | None:
    """Map a video/x-raw buffer to HxWx3 uint8 RGB (copy)."""
    fields = _caps_video_fields(caps) if caps is not None else None
    if fields is None:
        fields = _guess_fields_from_size(buf.get_size(), width=width, height=height)
    if fields is None:
        return None
    w, h, fmt, stride = fields
    success, map_info = buf.map(Gst.MapFlags.READ)
    if not success:
        return None
    try:
        data = np.frombuffer(map_info.data, dtype=np.uint8)
        if fmt == "RGB":
            row = w * 3
            if stride == row:
                return data.reshape((h, w, 3)).copy()
            out = np.empty((h, w, 3), dtype=np.uint8)
            for y in range(h):
                out[y] = data[y * stride : y * stride + row].reshape((w, 3))
            return out
        if fmt in ("RGBA", "RGBx"):
            row = w * 4
            if stride == row:
                return data.reshape((h, w, 4))[:, :, :3].copy()
            out = np.empty((h, w, 3), dtype=np.uint8)
            for y in range(h):
                out[y] = data[y * stride : y * stride + row].reshape((w, 4))[:, :3]
            return out
        if fmt in ("BGRA", "BGRx"):
            row = w * 4
            if stride == row:
                return data.reshape((h, w, 4))[:, :, :3][:, :, ::-1].copy()
            out = np.empty((h, w, 3), dtype=np.uint8)
            for y in range(h):
                out[y] = data[y * stride : y * stride + row].reshape((w, 4))[:, :3][:, ::-1]
            return out
        if fmt == "BGR":
            row = w * 3
            if stride == row:
                bgr = data.reshape((h, w, 3))
            else:
                bgr = np.empty((h, w, 3), dtype=np.uint8)
                for y in range(h):
                    bgr[y] = data[y * stride : y * stride + row].reshape((w, 3))
            return bgr[:, :, ::-1].copy()
        key = f"{w}x{h}:{fmt}"
        if key not in _warned_formats:
            _warned_formats.add(key)
            logger.warning("thumbnail probe: unsupported pixel format %s", fmt)
        return None
    finally:
        buf.unmap(map_info)


def make_resize_thumbnail_probe(
    camera_index: int,
    on_frame: Callable[[int, np.ndarray], None],
    *,
    width: int,
    height: int,
    min_interval_sec: float = 0.0,
) -> Callable[..., Any]:
    """Probe callback on resize_caps src — same pixels fed toward nvinfer."""
    last_at = 0.0

    def _probe(pad: Gst.Pad, info: Gst.PadProbeInfo, _user_data: object) -> Gst.PadProbeReturn:
        nonlocal last_at
        now = time.monotonic()
        if min_interval_sec > 0 and now - last_at < min_interval_sec:
            return Gst.PadProbeReturn.OK
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.OK
        caps = pad.get_current_caps()
        try:
            rgb = gst_buffer_to_rgb(buf, caps, width=width, height=height)
        except Exception:
            logger.exception("thumbnail probe cam%d failed", camera_index)
            return Gst.PadProbeReturn.OK
        if rgb is not None:
            if min_interval_sec > 0:
                last_at = now
            on_frame(camera_index, rgb)
        return Gst.PadProbeReturn.OK

    return _probe


def attach_resize_thumbnail_probe(
    element: Any,
    camera_index: int,
    on_frame: Callable[[int, np.ndarray], None],
    *,
    width: int,
    height: int,
    min_interval_sec: float = 0.0,
) -> None:
    """Attach BUFFER probe on element src pad (e.g. resize_caps after debayer+scale)."""
    pad = element.get_static_pad("src")
    if pad is None:
        raise RuntimeError(f"thumbnail probe: src pad missing on cam{camera_index}")
    pad.add_probe(
        Gst.PadProbeType.BUFFER,
        make_resize_thumbnail_probe(
            camera_index,
            on_frame,
            width=width,
            height=height,
            min_interval_sec=min_interval_sec,
        ),
        None,
    )
