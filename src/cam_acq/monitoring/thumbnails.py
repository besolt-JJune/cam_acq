"""Latest resize JPEG per camera for MJPEG dashboard streams."""

from __future__ import annotations

import io
import threading

import numpy as np
from PIL import Image

_JPEG_QUALITY = 88
_PLACEHOLDER: bytes | None = None


class ThumbnailStore:
    """Thread-safe latest JPEG per camera (YOLO resize resolution, not 4K)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: dict[int, bytes] = {}

    def update_rgb(self, camera_index: int, rgb: np.ndarray) -> None:
        """Encode RGB uint8 HxWx3 array to JPEG and cache."""
        if rgb is None or rgb.size == 0:
            return
        img = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
        with self._lock:
            self._jpeg[camera_index] = buf.getvalue()

    def get_jpeg(self, camera_index: int) -> bytes | None:
        """Return cached JPEG or None."""
        with self._lock:
            return self._jpeg.get(camera_index)

    def has_camera(self, camera_index: int) -> bool:
        with self._lock:
            return camera_index in self._jpeg


def placeholder_jpeg() -> bytes:
    """Valid minimal JPEG until the first live frame (MJPEG stream bootstrap only)."""
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (20, 24, 32)).save(buf, format="JPEG", quality=70)
        _PLACEHOLDER = buf.getvalue()
    return _PLACEHOLDER
