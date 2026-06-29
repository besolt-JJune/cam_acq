"""GStreamer DeepStream live pipeline: appsrc x N → YOLO nvinfer → OSD → optional MP4."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import typing_extensions  # noqa: F401 — pin venv before dist-packages prepend (pydantic Sentinel)

# ponytail: use distro PyGObject; uv venv often lacks gi (pycairo build)
for _p in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.12/dist-packages"):
    if Path(_p).is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

import numpy as np

from cam_acq.detection.gst_meta import LiveDetectionBridge, attach_nvinfer_detection_probe
from cam_acq.detection.gst_thumb import attach_resize_thumbnail_probe


def _ensure_gst_plugins() -> None:
    """Prepend DeepStream plugin dir when not already on GST_PLUGIN_PATH."""
    ds_plugins = "/opt/nvidia/deepstream/deepstream/lib/gst-plugins"
    if Path(ds_plugins).is_dir():
        prev = os.environ.get("GST_PLUGIN_PATH", "")
        if ds_plugins not in prev.split(":"):
            os.environ["GST_PLUGIN_PATH"] = f"{ds_plugins}:{prev}" if prev else ds_plugins


class DeepStreamYoloLive:
    """Feed RGB or Bayer frames into nvstreammux + nvinfer (batch = num_cameras)."""

    def __init__(
        self,
        *,
        num_cameras: int,
        width: int,
        height: int,
        fps: float,
        gpu_id: int,
        nvinfer_config: Path,
        record_path: Path | None,
        detection_bridge: LiveDetectionBridge | None = None,
        bayer_input: bool = False,
        bayer_width: int = 0,
        bayer_height: int = 0,
        bayer_gst_format: str = "rggb",
        on_yolo_input_frame: Callable[[int, np.ndarray], None] | None = None,
    ) -> None:
        if num_cameras < 1:
            raise ValueError("num_cameras must be >= 1")
        _ensure_gst_plugins()
        Gst.init(None)

        self.num_cameras = num_cameras
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_duration_ns = int(1_000_000_000 / fps)
        self._pts = 0
        self._bayer_input = bayer_input
        self._bayer_width = bayer_width
        self._bayer_height = bayer_height
        self._bayer_gst_format = bayer_gst_format
        self._nvinfer_config = nvinfer_config.resolve()
        self._record_path = record_path.resolve() if record_path else None
        self._detection_bridge = detection_bridge
        self._on_yolo_input_frame = on_yolo_input_frame

        self.pipeline = Gst.Pipeline.new("cam-acq-yolo-live")
        self.appsrcs: list[Gst.Element] = []
        mux = Gst.ElementFactory.make("nvstreammux", "mux")
        if mux is None:
            raise RuntimeError("nvstreammux not available (DeepStream plugins?)")
        mux.set_property("batch-size", num_cameras)
        mux.set_property("width", width)
        mux.set_property("height", height)
        mux.set_property("live-source", 1)
        mux.set_property("batched-push-timeout", 40_000)
        mux.set_property("gpu-id", gpu_id)
        self.pipeline.add(mux)

        caps_str = (
            f"video/x-bayer,format={bayer_gst_format},width={bayer_width},height={bayer_height},"
            f"framerate={int(fps)}/1"
            if bayer_input
            else f"video/x-raw,format=RGBA,width={width},height={height},framerate={int(fps)}/1"
        )
        for i in range(num_cameras):
            src = Gst.ElementFactory.make("appsrc", f"src{i}")
            if src is None:
                raise RuntimeError("failed to create appsrc")
            src.set_property("is-live", True)
            src.set_property("format", Gst.Format.TIME)
            src.set_property("block", True)
            src.set_property("caps", Gst.Caps.from_string(caps_str))

            if bayer_input:
                debayer = Gst.ElementFactory.make("bayer2rgb", f"debayer{i}")
                scale = Gst.ElementFactory.make("videoscale", f"scale{i}")
                resize_caps = Gst.ElementFactory.make("capsfilter", f"resize_caps{i}")
                convert = Gst.ElementFactory.make("videoconvert", f"convert{i}")
                nvconv = Gst.ElementFactory.make("nvvideoconvert", f"conv{i}")
                caps = Gst.ElementFactory.make("capsfilter", f"caps{i}")
                if not all((debayer, scale, resize_caps, convert, nvconv, caps)):
                    raise RuntimeError("failed to create bayer debayer/scale/nvvideoconvert chain")
                resize_caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"video/x-raw,width={width},height={height},framerate={int(fps)}/1"
                    ),
                )
                caps.set_property("caps", Gst.Caps.from_string("video/x-raw(memory:NVMM),format=NV12"))
                nvconv.set_property("gpu-id", gpu_id)
                for el in (src, debayer, scale, resize_caps, convert, nvconv, caps):
                    self.pipeline.add(el)
                if not src.link(debayer):
                    raise RuntimeError(f"link failed src{i}->debayer{i}")
                if not debayer.link(scale):
                    raise RuntimeError(f"link failed debayer{i}->scale{i}")
                if not scale.link(resize_caps):
                    raise RuntimeError(f"link failed scale{i}->resize_caps{i}")
                if not resize_caps.link(convert):
                    raise RuntimeError(f"link failed resize_caps{i}->convert{i}")
                if not convert.link(nvconv):
                    raise RuntimeError(f"link failed convert{i}->conv{i}")
                if not nvconv.link(caps):
                    raise RuntimeError(f"link failed conv{i}->caps{i}")
                if self._on_yolo_input_frame is not None:
                    attach_resize_thumbnail_probe(
                        resize_caps,
                        i,
                        self._on_yolo_input_frame,
                        width=self.width,
                        height=self.height,
                        min_interval_sec=0.0,
                    )
                tail_el = caps
            else:
                convert = Gst.ElementFactory.make("nvvideoconvert", f"conv{i}")
                caps = Gst.ElementFactory.make("capsfilter", f"caps{i}")
                if convert is None or caps is None:
                    raise RuntimeError("failed to create nvvideoconvert/capsfilter")
                caps.set_property("caps", Gst.Caps.from_string("video/x-raw(memory:NVMM),format=NV12"))
                convert.set_property("gpu-id", gpu_id)
                for el in (src, convert, caps):
                    self.pipeline.add(el)
                if not src.link(convert):
                    raise RuntimeError(f"link failed src{i}->conv{i}")
                if not convert.link(caps):
                    raise RuntimeError(f"link failed conv{i}->caps{i}")
                tail_el = caps

            sink_pad = mux.request_pad_simple(f"sink_{i}")
            if sink_pad is None:
                raise RuntimeError(f"mux sink_{i} pad missing")
            src_pad = tail_el.get_static_pad("src")
            if src_pad.link(sink_pad) != Gst.PadLinkReturn.OK:
                raise RuntimeError(f"link failed caps{i}->mux.sink_{i}")
            self.appsrcs.append(src)

        infer = Gst.ElementFactory.make("nvinfer", "infer")
        if infer is None:
            raise RuntimeError("nvinfer not available")
        infer.set_property("config-file-path", str(self._nvinfer_config))
        infer.set_property("gpu-id", gpu_id)
        self.pipeline.add(infer)
        if self._detection_bridge is not None:
            attach_nvinfer_detection_probe(infer, self._detection_bridge)

        tiler = Gst.ElementFactory.make("nvmultistreamtiler", "tiler")
        osd = Gst.ElementFactory.make("nvdsosd", "osd")
        if tiler is None or osd is None:
            raise RuntimeError("nvmultistreamtiler/nvdsosd not available")
        tiler.set_property("rows", 1)
        tiler.set_property("columns", num_cameras)
        tiler.set_property("width", width * num_cameras if num_cameras > 1 else width)
        tiler.set_property("height", height)
        tiler.set_property("gpu-id", gpu_id)
        osd.set_property("gpu-id", gpu_id)
        self.pipeline.add(tiler)
        self.pipeline.add(osd)

        tail: Gst.Element = osd
        if self._record_path:
            self._record_path.parent.mkdir(parents=True, exist_ok=True)
            enc = Gst.ElementFactory.make("nvv4l2h264enc", "enc")
            conv_enc = Gst.ElementFactory.make("nvvideoconvert", "conv_enc")
            parse = Gst.ElementFactory.make("h264parse", "parse")
            mux_mp4 = Gst.ElementFactory.make("qtmux", "qtmux")
            sink = Gst.ElementFactory.make("filesink", "filesink")
            if enc is None or conv_enc is None or parse is None or mux_mp4 is None or sink is None:
                raise RuntimeError("encoder/mux/filesink not available")
            enc.set_property("bitrate", 4_000_000)
            conv_enc.set_property("gpu-id", gpu_id)
            sink.set_property("location", str(self._record_path))
            for el in (conv_enc, enc, parse, mux_mp4, sink):
                self.pipeline.add(el)
            if not osd.link(conv_enc):
                raise RuntimeError("link osd->conv_enc failed")
            if not conv_enc.link(enc):
                raise RuntimeError("link conv_enc->enc failed")
            if not enc.link(parse):
                raise RuntimeError("link enc->parse failed")
            if not parse.link(mux_mp4):
                raise RuntimeError("link parse->qtmux failed")
            if not mux_mp4.link(sink):
                raise RuntimeError("link qtmux->filesink failed")
            tail = sink
        else:
            sink = Gst.ElementFactory.make("fakesink", "sink")
            if sink is None:
                raise RuntimeError("fakesink not available")
            sink.set_property("sync", False)
            self.pipeline.add(sink)
            if not osd.link(sink):
                raise RuntimeError("link osd->fakesink failed")

        if not mux.link(infer):
            raise RuntimeError("link mux->infer failed")
        if not infer.link(tiler):
            raise RuntimeError("link infer->tiler failed")
        if not tiler.link(osd):
            raise RuntimeError("link tiler->osd failed")

        self._bus = self.pipeline.get_bus()
        self._loop: GLib.MainLoop | None = None

    def start(self) -> None:
        """Set pipeline to PLAYING."""
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("pipeline failed to start")

    def stop(self, *, finalize_timeout_sec: float = 30.0) -> None:
        """End appsrc streams, wait for muxer EOS, then tear down (required for valid MP4)."""
        for src in self.appsrcs:
            src.emit("end-of-stream")
        if self._bus is not None:
            timeout_ns = int(finalize_timeout_sec * Gst.SECOND)
            msg = self._bus.timed_pop_filtered(
                timeout_ns,
                Gst.MessageType.EOS | Gst.MessageType.ERROR,
            )
            if msg is not None and msg.type == Gst.MessageType.ERROR:
                err, debug = msg.parse_error()
                raise RuntimeError(f"pipeline finalize error: {err.message} ({debug})")
        self.pipeline.set_state(Gst.State.NULL)

    def push_batch(self, frames: list[np.ndarray]) -> None:
        """Push one RGB frame per camera (same PTS); appsrc caps are RGBA for 4-byte row stride."""
        if len(frames) != self.num_cameras:
            raise ValueError(f"expected {self.num_cameras} frames, got {len(frames)}")
        pts = self._pts
        dur = self.frame_duration_ns
        for i, (appsrc, frame) in enumerate(zip(self.appsrcs, frames)):
            if frame.shape != (self.height, self.width, 3):
                raise ValueError(f"bad frame shape {frame.shape}")
            # ponytail: RGB width*3 is often not 4-byte aligned (e.g. 1006→3018); use RGBA
            rgba = np.empty((self.height, self.width, 4), dtype=np.uint8)
            rgba[:, :, :3] = frame
            rgba[:, :, 3] = 255
            data = rgba.tobytes()
            buf = Gst.Buffer.new_allocate(None, len(data), None)
            buf.fill(0, data)
            buf.pts = pts
            buf.duration = dur
            ret = appsrc.emit("push-buffer", buf)
            if ret != Gst.FlowReturn.OK:
                raise RuntimeError(f"appsrc push-buffer failed: {ret}")
            if self._on_yolo_input_frame is not None:
                self._on_yolo_input_frame(i, frame)
        self._pts += dur

    def push_bayer_batch(self, frames: list) -> None:
        """Push one full-resolution Bayer frame per camera (gpu_phase3 path)."""
        if not self._bayer_input:
            raise RuntimeError("pipeline was not built for Bayer input")
        if len(frames) != self.num_cameras:
            raise ValueError(f"expected {self.num_cameras} frames, got {len(frames)}")
        pts = self._pts
        dur = self.frame_duration_ns
        for appsrc, frame in zip(self.appsrcs, frames):
            if frame.width != self._bayer_width or frame.height != self._bayer_height:
                raise ValueError(
                    f"bayer size {frame.width}x{frame.height} != "
                    f"{self._bayer_width}x{self._bayer_height}"
                )
            data = frame.data
            buf = Gst.Buffer.new_allocate(None, len(data), None)
            buf.fill(0, data)
            buf.pts = pts
            buf.duration = dur
            ret = appsrc.emit("push-buffer", buf)
            if ret != Gst.FlowReturn.OK:
                raise RuntimeError(f"appsrc push-buffer failed: {ret}")
        self._pts += dur

    def poll_bus_errors(self) -> str | None:
        """Return first ERROR message string, if any."""
        if self._bus is None:
            return None
        msg = self._bus.pop_filtered(Gst.MessageType.ERROR)
        if msg is None:
            return None
        err, debug = msg.parse_error()
        return f"{err.message} ({debug})"
