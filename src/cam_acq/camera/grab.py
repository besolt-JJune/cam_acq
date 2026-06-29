"""Continuous grab and per-camera statistics for healthcheck."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from cam_acq.camera.device import close_camera, open_camera_by_ip
from cam_acq.config import CameraEndpoint, NOMINAL_FPS
from gxipy.gxidef import GxFrameStatusList, GxSwitchEntry


@dataclass
class GrabStats:
    """Aggregated grab metrics for one camera."""

    camera_index: int
    ip: str
    width: int = 0
    height: int = 0
    pixel_format: str = ""
    frames_received: int = 0
    incomplete_frames: int = 0
    frame_drops: int = 0
    last_frame_id: int | None = None
    last_timestamp: int | None = None
    timestamp_regressions: int = 0
    last_raw_image: Any = None
    open_error: str | None = None
    fps_avg: float = 0.0
    fps_min: float = 0.0
    _fps_window: list[float] = field(default_factory=list, repr=False)

    def record_frame(self, raw_image: Any) -> None:
        """Update counters from one RawImage."""
        self.frames_received += 1
        if raw_image.get_status() != GxFrameStatusList.SUCCESS:
            self.incomplete_frames += 1

        fid = raw_image.get_frame_id()
        if self.last_frame_id is not None and fid > self.last_frame_id + 1:
            self.frame_drops += int(fid - self.last_frame_id - 1)
        self.last_frame_id = fid

        ts = raw_image.get_timestamp()
        if self.last_timestamp is not None and ts < self.last_timestamp:
            self.timestamp_regressions += 1
        self.last_timestamp = ts
        self.last_raw_image = raw_image

    @property
    def timestamp_monotonic(self) -> bool:
        return self.timestamp_regressions == 0

    def finalize_fps(self, elapsed_sec: float) -> None:
        if elapsed_sec > 0:
            self.fps_avg = self.frames_received / elapsed_sec
        self.fps_min = min(self._fps_window) if self._fps_window else self.fps_avg


def _configure_continuous(cam: Any) -> None:
    """Continuous acquisition, trigger off (GigE)."""
    cam.TriggerMode.set(GxSwitchEntry.OFF)


def _read_geometry(cam: Any, fallback_w: int, fallback_h: int) -> tuple[int, int]:
    w = cam.Width.get() if cam.Width.is_readable() else fallback_w
    h = cam.Height.get() if cam.Height.is_readable() else fallback_h
    return int(w), int(h)


def grab_loop(
    endpoint: CameraEndpoint,
    stop_at: float,
    stats: GrabStats,
    pixel_format_label: str,
    fallback_w: int,
    fallback_h: int,
) -> None:
    """Open camera by IP, grab until stop_at monotonic time; fill stats."""
    cam = None
    try:
        cam = open_camera_by_ip(endpoint.ip)
        _configure_continuous(cam)
        w, h = _read_geometry(cam, fallback_w, fallback_h)
        stats.width = w
        stats.height = h
        stats.pixel_format = pixel_format_label
        cam.stream_on()

        window_start = time.monotonic()
        window_frames = 0
        while time.monotonic() < stop_at:
            raw = cam.data_stream[0].get_image(timeout=1000)
            if raw is None:
                continue
            stats.record_frame(raw)
            window_frames += 1
            now = time.monotonic()
            if now - window_start >= 1.0:
                stats._fps_window.append(window_frames / (now - window_start))
                window_start = now
                window_frames = 0
    except Exception as exc:
        stats.open_error = str(exc)
    finally:
        if cam is not None:
            try:
                cam.stream_off()
            except Exception:
                pass
        close_camera(cam)


def run_multi_grab(
    endpoints: tuple[CameraEndpoint, ...],
    duration_sec: float,
    pixel_format: str,
    fallback_w: int,
    fallback_h: int,
) -> list[GrabStats]:
    """Grab from all cameras in parallel threads for duration_sec."""
    stop_at = time.monotonic() + duration_sec
    stats_list = [
        GrabStats(camera_index=e.index, ip=e.ip) for e in endpoints
    ]
    threads = [
        threading.Thread(
            target=grab_loop,
            args=(ep, stop_at, st, pixel_format, fallback_w, fallback_h),
            daemon=True,
        )
        for ep, st in zip(endpoints, stats_list)
    ]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - start
    for st in stats_list:
        st.finalize_fps(elapsed)
    return stats_list


def min_frames_expected(duration_sec: float, nominal_fps: float = NOMINAL_FPS) -> int:
    """Healthcheck: expect at least 95% of nominal frame count."""
    return int(duration_sec * nominal_fps * 0.95)
