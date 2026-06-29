"""Recording controller: ring buffers, trigger windows, encode + metadata."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from cam_acq.camera.timesync import SessionTimeSync
from cam_acq.config import NOMINAL_FPS
from cam_acq.detection.events import DetectionFrameEvent, TriggerAction, TriggerDecision
from cam_acq.recording.buffer import (
    BayerRingBuffer,
    BufferedFrame,
    ring_capacity_frames,
    raw_image_to_buffered_frame,
)
from cam_acq.recording.gst_encode import encode_bayer_frames_to_mp4
from cam_acq.recording.metadata import write_frames_jsonl, write_session_json
from cam_acq.recording.storage import StorageManager


@dataclass(frozen=True)
class RecordedSegment:
    """Paths produced for one camera segment."""

    camera_index: int
    segment_index: int
    video_path: Path
    session_path: Path
    frames_path: Path
    frame_count: int


@dataclass
class RecordingController:
    """Per-camera Bayer rings; encode on trigger close (Phase 4)."""

    storage: StorageManager
    camera_indices: tuple[int, ...]
    buffer_sec: float
    split_interval_sec: float
    pixel_format: str
    bayer_format: str
    codec: str
    bitrate_bps: int
    gpu_id: int
    fps: float = NOMINAL_FPS
    _rings: dict[int, BayerRingBuffer] = field(default_factory=dict, init=False)
    _pending: TriggerDecision | None = field(default=None, init=False)
    _segments: list[RecordedSegment] = field(default_factory=list, init=False)
    _encoding: bool = field(default=False, init=False)
    _frame_events: dict[int, list[DetectionFrameEvent]] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        cap = ring_capacity_frames(self.fps, self.buffer_sec)
        for idx in self.camera_indices:
            self._rings[idx] = BayerRingBuffer(cap)

    def push_raw(self, camera_index: int, raw_image: Any) -> bool:
        """Copy one frame into the camera ring; return False if incomplete."""
        host_us = int(time.monotonic() * 1_000_000)
        frame = raw_image_to_buffered_frame(raw_image, host_recv_us=host_us)
        if frame is None:
            return False
        self._rings[camera_index].push(frame)
        return True

    def note_detection(self, event: DetectionFrameEvent) -> TriggerDecision | None:
        """Optional detection hook; stores frame events for metadata."""
        bucket = self._frame_events.setdefault(event.camera_index, [])
        bucket.append(event)
        return None

    def schedule_trigger(self, decision: TriggerDecision) -> None:
        """Queue trigger; manual overrides auto, auto never replaces manual pending."""
        if not decision.manual and self._pending is not None and self._pending.manual:
            return
        self._pending = decision

    def apply_trigger_action(self, action: TriggerAction) -> None:
        """Apply schedule / extend / finalize from RecordingTrigger."""
        if action.kind == "schedule":
            if action.decision is None:
                return
            self.schedule_trigger(action.decision)
        elif action.kind == "extend_end":
            if (
                action.ended_at_host_us is None
                or self._pending is None
                or self._pending.manual
            ):
                return
            self._pending = replace(
                self._pending, ended_at_host_us=action.ended_at_host_us
            )
        elif action.kind == "finalize_end":
            if action.ended_at_host_us is None or self._pending is None:
                return
            self._pending = replace(
                self._pending, ended_at_host_us=action.ended_at_host_us
            )

    def pending_ready(self, now_host_us: int | None = None) -> bool:
        """True when session end time passed (ended_at includes event silence tail)."""
        if self._pending is None:
            return False
        now = int(time.monotonic() * 1_000_000) if now_host_us is None else now_host_us
        return now >= self._pending.ended_at_host_us

    def take_pending_window_frames(
        self,
    ) -> tuple[TriggerDecision, dict[int, list[BufferedFrame]]] | None:
        """Return pre/trigger/post window frames and clear pending without encoding."""
        if self._pending is None:
            return None
        decision = self._pending
        self._pending = None
        pre_us = int(self.buffer_sec * 1_000_000)
        win_start = decision.started_at_host_us - pre_us
        win_end = decision.ended_at_host_us
        frames = {
            idx: self._rings[idx].frames_in_host_window(win_start, win_end)
            for idx in decision.camera_indices
        }
        return decision, frames

    def flush_pending(
        self,
        *,
        time_sync: SessionTimeSync,
        tick_frequency_hz: int = 1_000_000_000,
    ) -> list[RecordedSegment]:
        """Encode pending trigger for all channels; clear pending."""
        if self._pending is None:
            return []
        self._encoding = True
        try:
            decision = self._pending
            self._pending = None
            pre_us = int(self.buffer_sec * 1_000_000)
            win_start = decision.started_at_host_us - pre_us
            win_end = decision.ended_at_host_us
            return self._encode_window(
                decision=decision,
                win_start_us=win_start,
                win_end_us=win_end,
                time_sync=time_sync,
                tick_frequency_hz=tick_frequency_hz,
            )
        finally:
            self._encoding = False

    def status_snapshot(self, *, manual_active: bool = False) -> dict[str, Any]:
        """Monitoring: idle | recording | post_buffer | ready_to_flush | encoding."""
        if self._encoding:
            state = "encoding"
        elif self._pending is None:
            state = "idle"
        elif self.pending_ready():
            state = "ready_to_flush"
        elif manual_active:
            state = "recording"
        else:
            state = "post_buffer"
        pending_dict = self._pending.as_dict() if self._pending else None
        return {
            "state": state,
            "pending": pending_dict,
            "segments_written": len(self._segments),
            "buffer_sec": self.buffer_sec,
        }

    def _encode_window(
        self,
        *,
        decision: TriggerDecision,
        win_start_us: int,
        win_end_us: int,
        time_sync: SessionTimeSync,
        tick_frequency_hz: int,
    ) -> list[RecordedSegment]:
        split_us = int(self.split_interval_sec * 1_000_000)
        segments: list[tuple[int, int, int]] = []
        seg_idx = 0
        t = win_start_us
        while t < win_end_us:
            seg_end = min(t + split_us, win_end_us)
            segments.append((seg_idx, t, seg_end))
            seg_idx += 1
            t = seg_end

        out: list[RecordedSegment] = []
        loc = self.storage.location
        self.storage.maybe_fifo_cleanup()
        ts_meta = _time_sync_meta(time_sync, tick_frequency_hz)

        for segment_index, seg_start, seg_end in segments:
            # ponytail: one wall-clock anchor per segment — not per-camera encode time
            segment_when = time_sync.monotonic_us_to_epoch(seg_start)
            for camera_index in decision.camera_indices:
                all_frames = self._rings[camera_index].frames_in_host_window(
                    win_start_us, win_end_us
                )
                frames = [f for f in all_frames if seg_start <= f.host_recv_us <= seg_end]
                if not frames:
                    continue
                basename = self.storage.make_basename(
                    camera_index=camera_index,
                    segment_index=segment_index,
                    when=segment_when,
                    manual=decision.manual,
                )
                paths = self.storage.segment_paths(basename)
                encode_bayer_frames_to_mp4(
                    frames,
                    output_path=paths["video"],
                    bayer_format=self.bayer_format,
                    fps=self.fps,
                    codec=self.codec,
                    bitrate_bps=self.bitrate_bps,
                    gpu_id=self.gpu_id,
                )
                frame_rows = _frame_rows(
                    frames,
                    camera_index=camera_index,
                    events=self._frame_events.get(camera_index, []),
                    tick_frequency_hz=tick_frequency_hz,
                )
                write_frames_jsonl(paths["frames"], frame_rows)
                write_session_json(
                    paths["session"],
                    camera_index=camera_index,
                    segment_index=segment_index,
                    video_file=paths["video"].name,
                    frames_file=paths["frames"].name,
                    codec=self.codec,
                    width=frames[0].width,
                    height=frames[0].height,
                    trigger=decision,
                    buffer_sec=self.buffer_sec,
                    split_interval_sec=self.split_interval_sec,
                    segment_start_host_us=seg_start,
                    segment_end_host_us=seg_end,
                    storage_path=str(loc.path),
                    storage_fallback=loc.is_fallback,
                    time_sync=ts_meta,
                )
                seg = RecordedSegment(
                    camera_index=camera_index,
                    segment_index=segment_index,
                    video_path=paths["video"],
                    session_path=paths["session"],
                    frames_path=paths["frames"],
                    frame_count=len(frames),
                )
                out.append(seg)
                self._segments.append(seg)
        return out

    def memory_report(self) -> dict[int, int]:
        """Bytes retained per camera ring."""
        return {idx: ring.memory_bytes() for idx, ring in self._rings.items()}


def _tick_to_us(tick: int, hz: int) -> int:
    if hz <= 0:
        return tick
    return int(tick * 1_000_000 / hz)


def _time_sync_meta(time_sync: SessionTimeSync, tick_frequency_hz: int) -> dict[str, Any]:
    anchor = time_sync.anchors[0] if time_sync.anchors else None
    return {
        "strategy": time_sync.strategy,
        "session_host_t0_us": time_sync.host_elapsed_us(time_sync.host_t0_monotonic),
        "camera_ts0_us": anchor.camera_ts0_us if anchor else None,
        "tick_frequency_hz": tick_frequency_hz,
        "timestamp_reset_at_session": time_sync.timestamp_reset_on_session,
    }


def _frame_rows(
    frames: list[BufferedFrame],
    *,
    camera_index: int,
    events: list[DetectionFrameEvent],
    tick_frequency_hz: int,
) -> list[dict[str, Any]]:
    by_id = {e.frame_id: e for e in events}
    rows: list[dict[str, Any]] = []
    for f in frames:
        ev = by_id.get(f.frame_id)
        dets = [d.as_frame_dict() for d in ev.detections] if ev else []
        rows.append(
            {
                "frame_id": f.frame_id,
                "timestamp_us": _tick_to_us(f.timestamp_tick, tick_frequency_hz),
                "host_recv_us": f.host_recv_us,
                "detections": dets,
                "recorded": True,
            }
        )
    return rows
