"""Full-resolution Bayer RAM ring buffer for pre/post recording windows."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque

from gxipy.gxidef import GxFrameStatusList


@dataclass(frozen=True)
class BufferedFrame:
    """One copied Bayer frame with host and camera timestamps."""

    frame_id: int
    timestamp_tick: int
    host_recv_us: int
    width: int
    height: int
    data: bytes


def raw_image_to_buffered_frame(raw_image: Any, *, host_recv_us: int) -> BufferedFrame | None:
    """Copy gxipy RawImage Bayer payload into a BufferedFrame."""
    if raw_image.get_status() != GxFrameStatusList.SUCCESS:
        return None
    payload = raw_image.get_data()
    if payload is None:
        return None
    return BufferedFrame(
        frame_id=int(raw_image.get_frame_id()),
        timestamp_tick=int(raw_image.get_timestamp()),
        host_recv_us=host_recv_us,
        width=int(raw_image.get_width()),
        height=int(raw_image.get_height()),
        data=bytes(payload),
    )


def ring_capacity_frames(fps: float, buffer_sec: float) -> int:
    """Frames to retain: pre + event + post (3× RECORDING_BUFFER_SEC)."""
    return max(1, int(fps * buffer_sec * 3) + 5)


def recording_ring_capacity_frames(
    fps: float,
    buffer_sec: float,
    split_interval_sec: float,
) -> int:
    """Ring size for live recording with incremental split flush.

    Long ``split_interval_sec`` uses a small ring + periodic flush (see
  ``incremental_flush_chunk_sec``); short splits fit pre + split + post in RAM.
    """
    ring_sec = buffer_sec * 2 + split_interval_sec
    default_cap = ring_capacity_frames(fps, buffer_sec)
    if ring_sec > buffer_sec * 3:
        return default_cap
    return max(1, int(fps * ring_sec) + 5)


def incremental_flush_chunk_sec(
    fps: float,
    buffer_sec: float,
    split_interval_sec: float,
) -> float:
    """Wall-clock span per incremental encode while a session is open."""
    cap = recording_ring_capacity_frames(fps, buffer_sec, split_interval_sec)
    retention_sec = cap / fps if fps > 0 else buffer_sec
    return max(1.0, retention_sec - 2 * buffer_sec)


def split_segments_in_host_window(
    *,
    anchor_us: int,
    range_start_us: int,
    range_end_us: int,
    split_interval_sec: float,
) -> list[tuple[int, int, int]]:
    """``(segment_index, seg_start_us, seg_end_us)`` aligned to split from anchor."""
    if range_end_us <= range_start_us:
        return []
    split_us = int(split_interval_sec * 1_000_000)
    if split_us <= 0:
        return [(0, range_start_us, range_end_us)]
    out: list[tuple[int, int, int]] = []
    t = range_start_us
    while t < range_end_us:
        seg_idx = int((t - anchor_us) // split_us)
        boundary_start = anchor_us + seg_idx * split_us
        seg_start = max(t, boundary_start)
        seg_end = min(anchor_us + (seg_idx + 1) * split_us, range_end_us)
        if seg_start < seg_end:
            out.append((seg_idx, seg_start, seg_end))
        t = seg_end
    return out


def segment_bounds_us(
    anchor_us: int,
    segment_index: int,
    split_interval_sec: float,
) -> tuple[int, int]:
    """Host-time [start, end) for a split segment index from session anchor."""
    split_us = int(split_interval_sec * 1_000_000)
    start = anchor_us + segment_index * split_us
    return start, start + split_us


def segment_index_at(anchor_us: int, host_us: int, split_interval_sec: float) -> int:
    """Split segment index for a host monotonic timestamp."""
    split_us = int(split_interval_sec * 1_000_000)
    if split_us <= 0:
        return 0
    return int((host_us - anchor_us) // split_us)


@dataclass(frozen=True)
class RingPushResult:
    """Result of one ring push (whether an older frame was evicted)."""

    evicted: bool


class BayerRingBuffer:
    """Thread-safe deque ring; oldest frames drop when full."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._frames: Deque[BufferedFrame] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._push_total = 0
        self._overflow_drops = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def push_total(self) -> int:
        with self._lock:
            return self._push_total

    @property
    def overflow_drops(self) -> int:
        with self._lock:
            return self._overflow_drops

    def push(self, frame: BufferedFrame) -> RingPushResult:
        """Append frame; evict oldest when at capacity."""
        with self._lock:
            evicted = len(self._frames) >= self._capacity
            if evicted:
                self._overflow_drops += 1
            self._push_total += 1
            self._frames.append(frame)
            return RingPushResult(evicted=evicted)

    def oldest_host_recv_us(self) -> int | None:
        """Host timestamp of oldest retained frame, if any."""
        with self._lock:
            if not self._frames:
                return None
            return self._frames[0].host_recv_us

    def fill_ratio(self) -> float:
        with self._lock:
            return len(self._frames) / self._capacity

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

    def frames_in_host_window(self, start_us: int, end_us: int) -> list[BufferedFrame]:
        """Return frames with host_recv_us in [start_us, end_us], time-ordered."""
        with self._lock:
            selected = [f for f in self._frames if start_us <= f.host_recv_us <= end_us]
        return sorted(selected, key=lambda f: f.host_recv_us)

    def memory_bytes(self) -> int:
        with self._lock:
            return sum(len(f.data) for f in self._frames)
