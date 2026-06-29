"""GStreamer pad probe: nvinfer NvDsBatchMeta → detection events + trigger."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from cam_acq.detection.bbox import BBox, RawDetection
from cam_acq.detection.events import (
    DetectionFrameEvent,
    RecordingTrigger,
    TriggerDecision,
    build_detection_event_from_mux,
)
from cam_acq.detection.pyds_loader import import_pyds

if TYPE_CHECKING:
    from gi.repository import Gst

    from cam_acq.recording.controller import RecordingController


@dataclass
class LiveDetectionBridge:
    """Thread-safe bridge from nvinfer probe to RecordingTrigger (Phase 3 live)."""

    resize_w: int
    resize_h: int
    camera_w: int
    camera_h: int
    confidence_threshold: float
    trigger: RecordingTrigger
    recording: RecordingController | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    frames_with_meta: int = 0
    person_frame_hits: int = 0
    trigger_decisions: list[dict] = field(default_factory=list)
    pyds_warning: str | None = None

    def snapshot(self) -> dict:
        """Summary for healthcheck JSON."""
        with self._lock:
            out = {
                "frames_with_meta": self.frames_with_meta,
                "person_frame_hits": self.person_frame_hits,
                "trigger_events": list(self.trigger_decisions),
                "trigger_active_at_end": self.trigger.is_active,
            }
            if self.pyds_warning:
                out["pyds_warning"] = self.pyds_warning
            return out


def _iter_object_metas(pyds: Any, frame_meta: Any) -> list[RawDetection]:
    """Parse NvDsObjectMeta list into RawDetection (mux pixel coords)."""
    out: list[RawDetection] = []
    l_obj = frame_meta.obj_meta_list
    while l_obj is not None:
        try:
            obj = pyds.NvDsObjectMeta.cast(l_obj.data)
        except StopIteration:
            break
        rect = obj.rect_params
        out.append(
            RawDetection(
                class_id=int(obj.class_id),
                class_name=str(obj.obj_label or ""),
                confidence=float(obj.confidence),
                bbox=BBox(
                    x1=float(rect.left),
                    y1=float(rect.top),
                    x2=float(rect.left + rect.width),
                    y2=float(rect.top + rect.height),
                ),
            )
        )
        try:
            l_obj = l_obj.next
        except StopIteration:
            break
    return out


def make_nvinfer_src_probe(bridge: LiveDetectionBridge) -> Callable[..., Any]:
    """Return a Gst pad probe callback wired to bridge + RecordingTrigger."""

    pyds = import_pyds()
    from gi.repository import Gst  # noqa: WPS433 — runtime import after gi init

    def _probe(_pad: Gst.Pad, info: Gst.PadProbeInfo, _user_data: object) -> Gst.PadProbeReturn:
        gst_buffer = info.get_buffer()
        if gst_buffer is None:
            return Gst.PadProbeReturn.OK
        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
        if batch_meta is None:
            return Gst.PadProbeReturn.OK
        host_us = int(time.monotonic() * 1_000_000)
        l_frame = batch_meta.frame_meta_list
        while l_frame is not None:
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break
            raw = _iter_object_metas(pyds, frame_meta)
            event: DetectionFrameEvent = build_detection_event_from_mux(
                camera_index=int(frame_meta.pad_index),
                frame_id=int(frame_meta.frame_num),
                timestamp_us=int(frame_meta.buf_pts / 1000) if frame_meta.buf_pts else 0,
                host_recv_us=host_us,
                raw=raw,
                resize_w=bridge.resize_w,
                resize_h=bridge.resize_h,
                camera_w=bridge.camera_w,
                camera_h=bridge.camera_h,
                confidence_threshold=bridge.confidence_threshold,
            )
            with bridge._lock:
                bridge.frames_with_meta += 1
                if event.has_person:
                    bridge.person_frame_hits += 1
                if bridge.recording is not None:
                    bridge.recording.note_detection(event)
                decision: TriggerDecision | None = bridge.trigger.on_detection(
                    event, host_recv_us=host_us
                )
                if decision is not None:
                    bridge.trigger_decisions.append(decision.as_dict())
                    if bridge.recording is not None:
                        bridge.recording.schedule_trigger(decision)
            try:
                l_frame = l_frame.next
            except StopIteration:
                break
        return Gst.PadProbeReturn.OK

    return _probe


def attach_nvinfer_detection_probe(infer: Any, bridge: LiveDetectionBridge) -> None:
    """Attach probe on nvinfer src pad; no-op with warning if pyds is missing."""
    from gi.repository import Gst  # noqa: WPS433

    try:
        probe = make_nvinfer_src_probe(bridge)
    except ImportError as exc:
        bridge.pyds_warning = str(exc)
        return
    pad = infer.get_static_pad("src")
    if pad is None:
        raise RuntimeError("nvinfer src pad missing")
    pad.add_probe(Gst.PadProbeType.BUFFER, probe, None)
