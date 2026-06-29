"""Self-check gst_buffer_to_rgb without live camera."""

from __future__ import annotations

import sys
from pathlib import Path

for _p in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.12/dist-packages"):
    if Path(_p).is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

import numpy as np

from cam_acq.detection.gst_thumb import gst_buffer_to_rgb


def test_rgb_buffer_roundtrip():
    Gst.init(None)
    w, h = 96, 54
    src = np.zeros((h, w, 3), dtype=np.uint8)
    src[10, 20] = (10, 20, 30)
    caps = Gst.Caps.from_string(f"video/x-raw,format=RGB,width={w},height={h}")
    buf = Gst.Buffer.new_allocate(None, src.nbytes, None)
    buf.fill(0, src.tobytes())
    out = gst_buffer_to_rgb(buf, caps)
    assert out is not None
    assert out.shape == (h, w, 3)
    assert tuple(out[10, 20]) == (10, 20, 30)


def test_rgbx_size_guess():
    Gst.init(None)
    w, h = 1006, 760
    data = np.zeros((h, w, 4), dtype=np.uint8).tobytes()
    buf = Gst.Buffer.new_allocate(None, len(data), None)
    buf.fill(0, data)
    out = gst_buffer_to_rgb(buf, None, width=w, height=h)
    assert out is not None
    assert out.shape == (h, w, 3)


def test_bgrx_size_guess():
    Gst.init(None)
    w, h = 1006, 760
    src = np.zeros((h, w, 4), dtype=np.uint8)
    src[:, :, 0] = 10
    src[:, :, 1] = 20
    src[:, :, 2] = 30
    buf = Gst.Buffer.new_allocate(None, src.nbytes, None)
    buf.fill(0, src.tobytes())
    caps = Gst.Caps.from_string(f"video/x-raw,format=BGRx,width={w},height={h}")
    out = gst_buffer_to_rgb(buf, caps)
    assert out is not None
    assert out.shape == (h, w, 3)
    assert tuple(out[0, 0]) == (30, 20, 10)


if __name__ == "__main__":
    test_rgb_buffer_roundtrip()
    test_rgbx_size_guess()
    test_bgrx_size_guess()
    print("ok")
