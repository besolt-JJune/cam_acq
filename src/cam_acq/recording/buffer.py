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


class BayerRingBuffer:
    """Thread-safe deque ring; oldest frames drop when full."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._frames: Deque[BufferedFrame] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def push(self, frame: BufferedFrame) -> None:
        with self._lock:
            self._frames.append(frame)

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
