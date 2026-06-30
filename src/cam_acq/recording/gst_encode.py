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


def _create_bayer_encode_pipeline(
    *,
    output_path: Path,
    width: int,
    height: int,
    bayer_format: str,
    fps: float,
    codec: str,
    bitrate_bps: int,
    gpu_id: int,
) -> tuple[Gst.Pipeline, Gst.Element, int]:
    """Build PLAYING Bayer→NVENC pipeline; caller owns lifecycle until EOS."""
    _ensure_gst_plugins()
    Gst.init(None)

    bayer_fmt = resolve_gst_bayer_format(bayer_format=bayer_format)
    frame_dur_ns = int(1_000_000_000 / fps)
    h265 = codec.upper() == "H265"
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
        f"video/x-bayer,format={bayer_fmt},width={width},height={height},"
        f"framerate={int(fps)}/1"
    )
    appsrc.set_property("is-live", True)
    appsrc.set_property("format", Gst.Format.TIME)
    appsrc.set_property("caps", Gst.Caps.from_string(caps_str))
    upload.set_property("cuda-device-id", gpu_id)
    enc.set_property("bitrate", max(1, bitrate_bps // 1000))
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
    return pipeline, appsrc, frame_dur_ns


class BayerSegmentEncoder:
    """Open NVENC MP4 for one split segment; push frames incrementally until finalize()."""

    def __init__(
        self,
        *,
        output_path: Path,
        width: int,
        height: int,
        bayer_format: str,
        fps: float,
        codec: str,
        bitrate_bps: int,
        gpu_id: int,
    ) -> None:
        self.output_path = output_path
        self._width = width
        self._height = height
        self._pipeline, self._appsrc, self._frame_dur_ns = _create_bayer_encode_pipeline(
            output_path=output_path,
            width=width,
            height=height,
            bayer_format=bayer_format,
            fps=fps,
            codec=codec,
            bitrate_bps=bitrate_bps,
            gpu_id=gpu_id,
        )
        self._pts = 0
        self._closed = False

    def push_frames(self, frames: list[BufferedFrame]) -> int:
        """Append Bayer frames to the open MP4; return count pushed."""
        if self._closed:
            raise RuntimeError("segment encoder already finalized")
        pushed = 0
        for frame in frames:
            if frame.width != self._width or frame.height != self._height:
                raise ValueError(
                    f"inconsistent frame size {frame.width}x{frame.height}"
                )
            buf = Gst.Buffer.new_allocate(None, len(frame.data), None)
            buf.fill(0, frame.data)
            buf.pts = self._pts
            buf.duration = self._frame_dur_ns
            self._pts += self._frame_dur_ns
            ret = self._appsrc.emit("push-buffer", buf)
            if ret != Gst.FlowReturn.OK:
                self.finalize()
                raise RuntimeError(f"appsrc push failed: {ret}")
            pushed += 1
        return pushed

    def finalize(self, *, timeout_sec: float = 120.0) -> None:
        """EOS and tear down pipeline (one MP4 per segment)."""
        if self._closed:
            return
        self._closed = True
        self._appsrc.emit("end-of-stream")
        bus = self._pipeline.get_bus()
        msg = bus.timed_pop_filtered(
            int(timeout_sec * Gst.SECOND),
            Gst.MessageType.EOS | Gst.MessageType.ERROR,
        )
        if msg is not None and msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            self._pipeline.set_state(Gst.State.NULL)
            raise RuntimeError(f"encode error: {err.message} ({debug})")
        self._pipeline.set_state(Gst.State.NULL)


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
    w, h = frames[0].width, frames[0].height
    enc = BayerSegmentEncoder(
        output_path=output_path,
        width=w,
        height=h,
        bayer_format=bayer_format,
        fps=fps,
        codec=codec,
        bitrate_bps=bitrate_bps,
        gpu_id=gpu_id,
    )
    enc.push_frames(frames)
    enc.finalize()
