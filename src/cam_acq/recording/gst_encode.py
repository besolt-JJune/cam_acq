"""GStreamer Bayer → debayer → CUDA upload → NVENC MP4 encoder."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typing_extensions  # noqa: F401 — pin venv before dist-packages prepend

for _p in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.12/dist-packages"):
    if Path(_p).is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from cam_acq.recording.buffer import BufferedFrame
from cam_acq.camera.bayer import resolve_gst_bayer_format


def _ensure_gst_plugins() -> None:
    ds_plugins = "/opt/nvidia/deepstream/deepstream/lib/gst-plugins"
    if Path(ds_plugins).is_dir():
        prev = os.environ.get("GST_PLUGIN_PATH", "")
        if ds_plugins not in prev.split(":"):
            os.environ["GST_PLUGIN_PATH"] = f"{ds_plugins}:{prev}" if prev else ds_plugins


def encode_bayer_frames_to_mp4(
    frames: list[BufferedFrame],
    *,
    output_path: Path,
    bayer_format: str,
    fps: float,
    codec: str,
    bitrate_bps: int,
    gpu_id: int = 0,
) -> None:
    """Encode copied Bayer frames to MP4 via bayer2rgb + cudaupload + NVENC."""
    if not frames:
        raise ValueError("no frames to encode")
    _ensure_gst_plugins()
    Gst.init(None)

    w, h = frames[0].width, frames[0].height
    bayer_fmt = resolve_gst_bayer_format(bayer_format=bayer_format)
    frame_dur_ns = int(1_000_000_000 / fps)
    h265 = codec.upper() == "H265"
    # ponytail: nvv4l2h264enc segfaults on bayer→NVMM NV12 at 4K; use nvcuda*enc instead
    enc_name = "nvcudah265enc" if h265 else "nvcudah264enc"
    parse_name = "h265parse" if h265 else "h264parse"

    pipeline = Gst.Pipeline.new("bayer-record")
    appsrc = Gst.ElementFactory.make("appsrc", "src")
    debayer = Gst.ElementFactory.make("bayer2rgb", "debayer")
    convert = Gst.ElementFactory.make("videoconvert", "convert")
    upload = Gst.ElementFactory.make("cudaupload", "upload")
    enc = Gst.ElementFactory.make(enc_name, "enc")
    parse = Gst.ElementFactory.make(parse_name, "parse")
    mux = Gst.ElementFactory.make("qtmux", "mux")
    sink = Gst.ElementFactory.make("filesink", "sink")
    if not all((appsrc, debayer, convert, upload, enc, parse, mux, sink)):
        raise RuntimeError("failed to create Bayer encode pipeline elements")

    caps_str = (
        f"video/x-bayer,format={bayer_fmt},width={w},height={h},framerate={int(fps)}/1"
    )
    appsrc.set_property("is-live", False)
    appsrc.set_property("format", Gst.Format.TIME)
    appsrc.set_property("caps", Gst.Caps.from_string(caps_str))
    upload.set_property("cuda-device-id", gpu_id)
    enc.set_property("bitrate", max(1, bitrate_bps // 1000))  # NVENC: kbit/sec
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sink.set_property("location", str(output_path.resolve()))

    for el in (appsrc, debayer, convert, upload, enc, parse, mux, sink):
        pipeline.add(el)
    if not appsrc.link(debayer):
        raise RuntimeError("link appsrc->bayer2rgb failed")
    if not debayer.link(convert):
        raise RuntimeError("link bayer2rgb->videoconvert failed")
    if not convert.link(upload):
        raise RuntimeError("link videoconvert->cudaupload failed")
    if not upload.link(enc):
        raise RuntimeError("link cudaupload->enc failed")
    if not enc.link(parse):
        raise RuntimeError("link enc->parse failed")
    if not parse.link(mux):
        raise RuntimeError("link parse->mux failed")
    if not mux.link(sink):
        raise RuntimeError("link mux->sink failed")

    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("encode pipeline failed to start")

    pts = 0
    for frame in frames:
        if frame.width != w or frame.height != h:
            raise ValueError(f"inconsistent frame size {frame.width}x{frame.height}")
        buf = Gst.Buffer.new_allocate(None, len(frame.data), None)
        buf.fill(0, frame.data)
        buf.pts = pts
        buf.duration = frame_dur_ns
        pts += frame_dur_ns
        ret = appsrc.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(f"appsrc push failed: {ret}")

    appsrc.emit("end-of-stream")
    bus = pipeline.get_bus()
    msg = bus.timed_pop_filtered(60 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    if msg is not None and msg.type == Gst.MessageType.ERROR:
        err, debug = msg.parse_error()
        pipeline.set_state(Gst.State.NULL)
        raise RuntimeError(f"encode error: {err.message} ({debug})")
    pipeline.set_state(Gst.State.NULL)
