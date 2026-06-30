"""Recording controller: ring buffers, trigger windows, encode + metadata."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TextIO

from cam_acq.camera.timesync import SessionTimeSync
from cam_acq.config import NOMINAL_FPS
from cam_acq.detection.events import DetectionFrameEvent, TriggerAction, TriggerDecision
from cam_acq.recording.buffer import (
    BayerRingBuffer,
    BufferedFrame,
    incremental_flush_chunk_sec,
    raw_image_to_buffered_frame,
    recording_ring_capacity_frames,
    segment_bounds_us,
    segment_index_at,
)
from cam_acq.recording.gst_encode import BayerSegmentEncoder
from cam_acq.recording.metadata import write_session_json
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
class RingCameraStats:
    """Per-camera ring/drain health (detect grab faster than encode drain)."""

    encoder_pushed: int = 0
    gap_events: int = 0
    gap_frames_est: int = 0
    max_fill_ratio: float = 0.0
    max_lag_sec: float = 0.0
    peak_memory_bytes: int = 0


@dataclass
class _OpenSegmentEncode:
    """One open NVENC file per (camera, split segment)."""

    camera_index: int
    segment_index: int
    seg_start_us: int
    seg_end_us: int
    encoder: BayerSegmentEncoder
    video_path: Path
    session_path: Path
    frames_path: Path
    frames_file: TextIO
    frame_count: int = 0
    width: int = 0
    height: int = 0


@dataclass
class RecordingController:
    """Per-camera Bayer rings; streaming NVENC per RECORDING_SPLIT_INTERVAL_SEC."""

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
    _frame_events: dict[int, list[DetectionFrameEvent]] = field(
        default_factory=dict, init=False
    )
    _session_anchor_us: int | None = field(default=None, init=False)
    _pushed_watermark_us: dict[int, int] = field(default_factory=dict, init=False)
    _open_segments: dict[int, _OpenSegmentEncode] = field(default_factory=dict, init=False)
    _last_drained_frame_id: dict[int, int] = field(default_factory=dict, init=False)
    _last_drained_host_us: dict[int, int] = field(default_factory=dict, init=False)
    _ring_stats: dict[int, RingCameraStats] = field(default_factory=dict, init=False)
    _finalize_threads: list[threading.Thread] = field(default_factory=list, init=False)
    _finalize_results: list[RecordedSegment] = field(default_factory=list, init=False)
    _finalize_errors: list[str] = field(default_factory=list, init=False)
    _finalize_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        cap = recording_ring_capacity_frames(
            self.fps, self.buffer_sec, self.split_interval_sec
        )
        for idx in self.camera_indices:
            self._rings[idx] = BayerRingBuffer(cap)
            self._ring_stats[idx] = RingCameraStats()

    @property
    def flush_chunk_sec(self) -> float:
        """Ring drain cadence hint (RAM retention, not file size)."""
        return incremental_flush_chunk_sec(
            self.fps, self.buffer_sec, self.split_interval_sec
        )

    def push_raw(self, camera_index: int, raw_image: Any) -> bool:
        """Copy one frame into the camera ring; return False if incomplete."""
        host_us = int(time.monotonic() * 1_000_000)
        frame = raw_image_to_buffered_frame(raw_image, host_recv_us=host_us)
        if frame is None:
            return False
        self._rings[camera_index].push(frame)
        self.sample_ring_health(camera_index, host_us=host_us)
        return True

    def sample_ring_health(self, camera_index: int, *, host_us: int | None = None) -> None:
        """Update peak fill/lag while grab or drain runs (thread-safe counters on ring)."""
        now = int(time.monotonic() * 1_000_000) if host_us is None else host_us
        ring = self._rings[camera_index]
        stats = self._ring_stats[camera_index]
        stats.max_fill_ratio = max(stats.max_fill_ratio, ring.fill_ratio())
        stats.peak_memory_bytes = max(stats.peak_memory_bytes, ring.memory_bytes())
        oldest = ring.oldest_host_recv_us()
        if oldest is not None and now > oldest:
            stats.max_lag_sec = max(stats.max_lag_sec, (now - oldest) / 1_000_000.0)

    def note_detection(self, event: DetectionFrameEvent) -> TriggerDecision | None:
        """Optional detection hook; stores frame events for metadata."""
        bucket = self._frame_events.setdefault(event.camera_index, [])
        bucket.append(event)
        return None

    def _reset_session_encode_state(self) -> None:
        """Drop open encoders without writing (only before a new session starts)."""
        for open_seg in list(self._open_segments.values()):
            try:
                open_seg.frames_file.close()
            except OSError:
                pass
            try:
                open_seg.encoder.finalize()
            except Exception:
                pass
            if open_seg.video_path.exists():
                open_seg.video_path.unlink(missing_ok=True)
            open_seg.frames_path.unlink(missing_ok=True)
            open_seg.session_path.unlink(missing_ok=True)
        self._open_segments.clear()
        self._pushed_watermark_us.clear()
        self._last_drained_frame_id.clear()
        self._last_drained_host_us.clear()
        self._join_finalize_threads()
        self._finalize_results.clear()
        self._finalize_errors.clear()
        for idx in self.camera_indices:
            self._ring_stats[idx] = RingCameraStats()

    def _begin_session_watermark(self, decision: TriggerDecision) -> None:
        """Anchor split segments for a new recording session."""
        self._reset_session_encode_state()
        pre_us = int(self.buffer_sec * 1_000_000)
        self._session_anchor_us = decision.started_at_host_us - pre_us

    def schedule_trigger(self, decision: TriggerDecision) -> None:
        """Queue trigger; manual overrides auto, auto never replaces manual pending."""
        if not decision.manual and self._pending is not None and self._pending.manual:
            return
        new_session = self._pending is None
        self._pending = decision
        if new_session:
            self._begin_session_watermark(decision)

    def apply_trigger_action(self, action: TriggerAction) -> None:
        """Apply schedule / extend / finalize from RecordingTrigger."""
        if action.kind == "schedule":
            if action.decision is None:
                return
            was_open = self._pending is not None
            self.schedule_trigger(action.decision)
            if was_open and action.decision.manual:
                self._begin_session_watermark(action.decision)
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

    @property
    def session_active(self) -> bool:
        """True while a trigger session is open and not yet ready to flush."""
        return self._pending is not None and not self.pending_ready()

    def pending_ready(self, now_host_us: int | None = None) -> bool:
        """True when session end time passed (ended_at includes event silence tail)."""
        if self._pending is None:
            return False
        now = int(time.monotonic() * 1_000_000) if now_host_us is None else now_host_us
        return now >= self._pending.ended_at_host_us

    def maybe_flush_incremental(
        self,
        *,
        time_sync: SessionTimeSync,
        tick_frequency_hz: int = 1_000_000_000,
        now_host_us: int | None = None,
    ) -> list[RecordedSegment]:
        """Drain ring into open segment encoders; finalize MP4 at each split boundary."""
        if (
            self._pending is None
            or self._session_anchor_us is None
            or self.pending_ready(now_host_us)
        ):
            return self._take_finalize_results()
        now = int(time.monotonic() * 1_000_000) if now_host_us is None else now_host_us
        for idx in self.camera_indices:
            self.sample_ring_health(idx, host_us=now)
        out = self._drain_rings(
            up_to_us=now,
            time_sync=time_sync,
            tick_frequency_hz=tick_frequency_hz,
            finalize_complete_segments=True,
        )
        out.extend(self._take_finalize_results())
        return out

    def _take_finalize_results(self) -> list[RecordedSegment]:
        """Return segments whose background NVENC finalize completed."""
        self._join_finalize_threads()
        with self._finalize_lock:
            out = list(self._finalize_results)
            self._finalize_results.clear()
        return out

    def _join_finalize_threads(self) -> None:
        for thread in self._finalize_threads:
            thread.join(timeout=300.0)
        self._finalize_threads.clear()

    def encode_errors(self) -> list[str]:
        """NVENC finalize failures from background threads."""
        self._join_finalize_threads()
        with self._finalize_lock:
            return list(self._finalize_errors)

    def take_pending_window_frames(
        self,
    ) -> tuple[TriggerDecision, dict[int, list[BufferedFrame]]] | None:
        """Return pre/trigger/post window frames and clear pending without encoding."""
        if self._pending is None:
            return None
        decision = self._pending
        self._pending = None
        self._reset_session_encode_state()
        self._session_anchor_us = None
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
        """Drain remainder and finalize all open segment files."""
        if self._pending is None:
            return []
        decision = self._pending
        win_end = decision.ended_at_host_us
        out = self._drain_rings(
            up_to_us=win_end,
            time_sync=time_sync,
            tick_frequency_hz=tick_frequency_hz,
            finalize_complete_segments=True,
        )
        for camera_index in list(self._open_segments.keys()):
            self._finalize_open_segment(
                camera_index,
                decision=decision,
                time_sync=time_sync,
                tick_frequency_hz=tick_frequency_hz,
            )
        self._pending = None
        self._session_anchor_us = None
        self._pushed_watermark_us.clear()
        out.extend(self._take_finalize_results())
        return out

    def status_snapshot(self, *, manual_active: bool = False) -> dict[str, Any]:
        """Monitoring: idle | recording | post_buffer | ready_to_flush | encoding."""
        if self._finalize_threads:
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
            "split_interval_sec": self.split_interval_sec,
            "flush_chunk_sec": self.flush_chunk_sec,
            "open_segment_indices": {
                cam: open_seg.segment_index
                for cam, open_seg in self._open_segments.items()
            },
        }

    def _drain_rings(
        self,
        *,
        up_to_us: int,
        time_sync: SessionTimeSync,
        tick_frequency_hz: int,
        finalize_complete_segments: bool,
    ) -> list[RecordedSegment]:
        if self._pending is None or self._session_anchor_us is None:
            return []
        decision = self._pending
        anchor_us = self._session_anchor_us
        out: list[RecordedSegment] = []
        for camera_index in decision.camera_indices:
            out.extend(
                self._drain_camera(
                    camera_index,
                    anchor_us=anchor_us,
                    up_to_us=up_to_us,
                    decision=decision,
                    time_sync=time_sync,
                    tick_frequency_hz=tick_frequency_hz,
                    finalize_complete_segments=finalize_complete_segments,
                )
            )
        return out

    def _drain_camera(
        self,
        camera_index: int,
        *,
        anchor_us: int,
        up_to_us: int,
        decision: TriggerDecision,
        time_sync: SessionTimeSync,
        tick_frequency_hz: int,
        finalize_complete_segments: bool,
    ) -> list[RecordedSegment]:
        wm = self._pushed_watermark_us.get(camera_index, anchor_us - 1)
        ring = self._rings[camera_index]
        frames = sorted(
            (
                f
                for f in ring.frames_in_host_window(wm + 1, up_to_us)
                if f.host_recv_us > wm
            ),
            key=lambda f: f.host_recv_us,
        )
        out: list[RecordedSegment] = []
        for frame in frames:
            seg_idx = segment_index_at(anchor_us, frame.host_recv_us, self.split_interval_sec)
            seg_start, seg_end = segment_bounds_us(anchor_us, seg_idx, self.split_interval_sec)
            open_seg = self._open_segments.get(camera_index)
            if open_seg is None or open_seg.segment_index != seg_idx:
                if open_seg is not None:
                    self._finalize_open_segment(
                        camera_index,
                        decision=decision,
                        time_sync=time_sync,
                        tick_frequency_hz=tick_frequency_hz,
                    )
                open_seg = self._open_segment_encoder(
                    camera_index=camera_index,
                    segment_index=seg_idx,
                    seg_start_us=seg_start,
                    seg_end_us=seg_end,
                    decision=decision,
                    time_sync=time_sync,
                    first_frame=frame,
                )
            self._push_frame_to_open_segment(
                open_seg,
                frame,
                tick_frequency_hz=tick_frequency_hz,
            )
            self._note_drained_frame(camera_index, frame)
            self._pushed_watermark_us[camera_index] = frame.host_recv_us

        if not finalize_complete_segments:
            return out

        open_seg = self._open_segments.get(camera_index)
        if open_seg is None:
            return out
        if up_to_us < open_seg.seg_end_us:
            return out
        pending = [
            f
            for f in ring.frames_in_host_window(open_seg.seg_start_us, open_seg.seg_end_us - 1)
            if f.host_recv_us > self._pushed_watermark_us.get(camera_index, anchor_us - 1)
        ]
        if pending:
            return out
        self._finalize_open_segment(
            camera_index,
            decision=decision,
            time_sync=time_sync,
            tick_frequency_hz=tick_frequency_hz,
        )
        return out

    def _open_segment_encoder(
        self,
        *,
        camera_index: int,
        segment_index: int,
        seg_start_us: int,
        seg_end_us: int,
        decision: TriggerDecision,
        time_sync: SessionTimeSync,
        first_frame: BufferedFrame,
    ) -> _OpenSegmentEncode:
        segment_when = time_sync.monotonic_us_to_epoch(seg_start_us)
        basename = self.storage.make_basename(
            camera_index=camera_index,
            segment_index=segment_index,
            when=segment_when,
            manual=decision.manual,
        )
        paths = self.storage.segment_paths(basename)
        encoder = BayerSegmentEncoder(
            output_path=paths["video"],
            width=first_frame.width,
            height=first_frame.height,
            bayer_format=self.bayer_format,
            fps=self.fps,
            codec=self.codec,
            bitrate_bps=self.bitrate_bps,
            gpu_id=self.gpu_id,
        )
        frames_file = paths["frames"].open("w", encoding="utf-8")
        open_seg = _OpenSegmentEncode(
            camera_index=camera_index,
            segment_index=segment_index,
            seg_start_us=seg_start_us,
            seg_end_us=seg_end_us,
            encoder=encoder,
            video_path=paths["video"],
            session_path=paths["session"],
            frames_path=paths["frames"],
            frames_file=frames_file,
            width=first_frame.width,
            height=first_frame.height,
        )
        self._open_segments[camera_index] = open_seg
        self.storage.maybe_fifo_cleanup()
        return open_seg

    def _push_frame_to_open_segment(
        self,
        open_seg: _OpenSegmentEncode,
        frame: BufferedFrame,
        *,
        tick_frequency_hz: int,
    ) -> None:
        open_seg.encoder.push_frames([frame])
        row = _frame_row(
            frame,
            camera_index=open_seg.camera_index,
            events=self._frame_events.get(open_seg.camera_index, []),
            tick_frequency_hz=tick_frequency_hz,
        )
        open_seg.frames_file.write(json.dumps(row, ensure_ascii=False) + "\n")
        open_seg.frame_count += 1

    def _finalize_open_segment(
        self,
        camera_index: int,
        *,
        decision: TriggerDecision,
        time_sync: SessionTimeSync,
        tick_frequency_hz: int,
    ) -> None:
        """Start background NVENC finalize so the grab/drain loop is not blocked."""
        open_seg = self._open_segments.pop(camera_index, None)
        if open_seg is None:
            return
        open_seg.frames_file.close()

        def _work() -> None:
            try:
                seg = self._finalize_segment_sync(
                    open_seg,
                    camera_index=camera_index,
                    decision=decision,
                    time_sync=time_sync,
                    tick_frequency_hz=tick_frequency_hz,
                )
                if seg is not None:
                    with self._finalize_lock:
                        self._finalize_results.append(seg)
                        self._segments.append(seg)
            except Exception as exc:
                with self._finalize_lock:
                    self._finalize_errors.append(
                        f"cam{camera_index} seg{open_seg.segment_index}: {exc}"
                    )

        thread = threading.Thread(target=_work, daemon=True)
        thread.start()
        self._finalize_threads.append(thread)

    def _finalize_segment_sync(
        self,
        open_seg: _OpenSegmentEncode,
        *,
        camera_index: int,
        decision: TriggerDecision,
        time_sync: SessionTimeSync,
        tick_frequency_hz: int,
    ) -> RecordedSegment | None:
        """Blocking NVENC EOS + session metadata (runs off the main loop)."""
        if open_seg.frame_count < 1:
            open_seg.encoder.finalize()
            open_seg.video_path.unlink(missing_ok=True)
            open_seg.frames_path.unlink(missing_ok=True)
            return None
        open_seg.encoder.finalize()
        loc = self.storage.location
        ts_meta = _time_sync_meta(time_sync, tick_frequency_hz)
        write_session_json(
            open_seg.session_path,
            camera_index=camera_index,
            segment_index=open_seg.segment_index,
            video_file=open_seg.video_path.name,
            frames_file=open_seg.frames_path.name,
            codec=self.codec,
            width=open_seg.width,
            height=open_seg.height,
            trigger=decision,
            buffer_sec=self.buffer_sec,
            split_interval_sec=self.split_interval_sec,
            segment_start_host_us=open_seg.seg_start_us,
            segment_end_host_us=open_seg.seg_end_us,
            storage_path=str(loc.path),
            storage_fallback=loc.is_fallback,
            time_sync=ts_meta,
        )
        return RecordedSegment(
            camera_index=camera_index,
            segment_index=open_seg.segment_index,
            video_path=open_seg.video_path,
            session_path=open_seg.session_path,
            frames_path=open_seg.frames_path,
            frame_count=open_seg.frame_count,
        )

    def _note_drained_frame(self, camera_index: int, frame: BufferedFrame) -> None:
        """Track encoder drain; estimate gaps when frame_id or host time jumps."""
        stats = self._ring_stats[camera_index]
        stats.encoder_pushed += 1
        last_id = self._last_drained_frame_id.get(camera_index)
        if last_id is not None and frame.frame_id > last_id + 1:
            gap = frame.frame_id - last_id - 1
            stats.gap_events += 1
            stats.gap_frames_est += gap
        last_us = self._last_drained_host_us.get(camera_index)
        frame_us = int(1_000_000 / self.fps) if self.fps > 0 else 50_000
        if last_us is not None and frame.host_recv_us - last_us > int(frame_us * 1.5):
            time_gap = int((frame.host_recv_us - last_us) / frame_us) - 1
            if time_gap > 0 and (last_id is None or frame.frame_id <= last_id + 1):
                stats.gap_events += 1
                stats.gap_frames_est += time_gap
        self._last_drained_frame_id[camera_index] = frame.frame_id
        self._last_drained_host_us[camera_index] = frame.host_recv_us

    def ring_stats_report(self) -> dict[str, Any]:
        """Ring overflow + drain lag summary for healthcheck JSON."""
        per_cam: dict[str, Any] = {}
        total_overflow = 0
        total_gap_est = 0
        encode_errors = self.encode_errors()
        cap = next(iter(self._rings.values())).capacity if self._rings else 0
        retention_sec = cap / self.fps if self.fps > 0 and cap else 0.0
        for idx in sorted(self.camera_indices):
            ring = self._rings[idx]
            stats = self._ring_stats[idx]
            overflow = ring.overflow_drops
            total_overflow += overflow
            total_gap_est += stats.gap_frames_est
            per_cam[str(idx)] = {
                "ring_capacity_frames": ring.capacity,
                "ring_push_total": ring.push_total,
                "ring_overflow_drops": overflow,
                "encoder_pushed_total": stats.encoder_pushed,
                "drain_gap_events": stats.gap_events,
                "drain_gap_frames_est": stats.gap_frames_est,
                "max_ring_fill_ratio": round(stats.max_fill_ratio, 4),
                "max_ring_lag_sec": round(stats.max_lag_sec, 3),
                "peak_ring_memory_bytes": stats.peak_memory_bytes,
            }
        return {
            "ring_retention_sec": round(retention_sec, 3),
            "flush_chunk_sec": round(self.flush_chunk_sec, 3),
            "split_interval_sec": self.split_interval_sec,
            "overflow_drops_total": total_overflow,
            "drain_gap_frames_est_total": total_gap_est,
            "encode_errors": encode_errors,
            "healthy": total_overflow == 0 and total_gap_est == 0 and not encode_errors,
            "cameras": per_cam,
        }

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


def _frame_row(
    frame: BufferedFrame,
    *,
    camera_index: int,
    events: list[DetectionFrameEvent],
    tick_frequency_hz: int,
) -> dict[str, Any]:
    by_id = {e.frame_id: e for e in events}
    ev = by_id.get(frame.frame_id)
    dets = [d.as_frame_dict() for d in ev.detections] if ev else []
    return {
        "frame_id": frame.frame_id,
        "timestamp_us": _tick_to_us(frame.timestamp_tick, tick_frequency_hz),
        "host_recv_us": frame.host_recv_us,
        "detections": dets,
        "recorded": True,
    }
