"""Single-frame Bayer8 → RGB via GStreamer bayer2rgb (pattern check, previews)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import typing_extensions  # noqa: F401 — pin venv before dist-packages prepend

for _p in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.12/dist-packages"):
    if Path(_p).is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402


def _ensure_gst_plugins() -> None:
    ds_plugins = "/opt/nvidia/deepstream/deepstream/lib/gst-plugins"
    if Path(ds_plugins).is_dir():
        prev = os.environ.get("GST_PLUGIN_PATH", "")
        if ds_plugins not in prev.split(":"):
            os.environ["GST_PLUGIN_PATH"] = f"{ds_plugins}:{prev}" if prev else ds_plugins


def bayer8_to_rgb(
    data: bytes,
    *,
    width: int,
    height: int,
    gst_bayer_format: str,
) -> np.ndarray:
    """Demosaic one Bayer8 frame to HxWx3 uint8 RGB using GStreamer bayer2rgb."""
    if len(data) != width * height:
        raise ValueError(f"expected {width * height} bytes, got {len(data)}")
    _ensure_gst_plugins()
    Gst.init(None)

    pipeline = Gst.Pipeline.new("bayer-debayer")
    appsrc = Gst.ElementFactory.make("appsrc", "src")
    debayer = Gst.ElementFactory.make("bayer2rgb", "debayer")
    convert = Gst.ElementFactory.make("videoconvert", "convert")
    caps = Gst.ElementFactory.make("capsfilter", "caps")
    appsink = Gst.ElementFactory.make("appsink", "sink")
    if not all((appsrc, debayer, convert, caps, appsink)):
        raise RuntimeError("failed to create bayer debayer pipeline")

    caps_str = (
        f"video/x-bayer,format={gst_bayer_format},width={width},height={height},framerate=1/1"
    )
    appsrc.set_property("caps", Gst.Caps.from_string(caps_str))
    appsrc.set_property("format", Gst.Format.TIME)
    appsrc.set_property("is-live", False)
    caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGB"))
    appsink.set_property("emit-signals", False)
    appsink.set_property("max-buffers", 1)
    appsink.set_property("drop", True)

    for el in (appsrc, debayer, convert, caps, appsink):
        pipeline.add(el)
    if not appsrc.link(debayer):
        raise RuntimeError("link appsrc->bayer2rgb failed")
    if not debayer.link(convert):
        raise RuntimeError("link bayer2rgb->videoconvert failed")
    if not convert.link(caps):
        raise RuntimeError("link videoconvert->caps failed")
    if not caps.link(appsink):
        raise RuntimeError("link caps->appsink failed")

    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("debayer pipeline failed to start")

    buf = Gst.Buffer.new_allocate(None, len(data), None)
    buf.fill(0, data)
    buf.pts = 0
    buf.duration = Gst.SECOND
    ret = appsrc.emit("push-buffer", buf)
    if ret != Gst.FlowReturn.OK:
        pipeline.set_state(Gst.State.NULL)
        raise RuntimeError(f"appsrc push failed: {ret}")
    appsrc.emit("end-of-stream")

    sample = appsink.emit("try-pull-sample", Gst.SECOND * 10)
    pipeline.set_state(Gst.State.NULL)
    if sample is None:
        raise RuntimeError("debayer appsink timeout")

    out_buf = sample.get_buffer()
    if out_buf is None:
        raise RuntimeError("empty debayer output")
    success, map_info = out_buf.map(Gst.MapFlags.READ)
    if not success:
        raise RuntimeError("failed to map debayer output")
    try:
        rgb = np.frombuffer(map_info.data, dtype=np.uint8).reshape((height, width, 3)).copy()
    finally:
        out_buf.unmap(map_info)
    return rgb
