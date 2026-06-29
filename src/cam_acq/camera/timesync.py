"""Host-clock session sync: TimestampReset anchors + monotonic host time."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from cam_acq.camera.timestamp import (
    TimestampCameraReport,
    probe_timestamp_readonly,
    reset_all_timestamps,
)
from cam_acq.config import CameraEndpoint


@dataclass(frozen=True)
class CameraTimeAnchor:
    """Per-camera timestamp anchor at session start."""

    camera_index: int
    ip: str
    camera_ts0: int | None
    tick_frequency_hz: int | None
    reset_performed: bool
    open_error: str | None = None
    reset_error: str | None = None

    @property
    def camera_ts0_us(self) -> int | None:
        if self.camera_ts0 is None or not self.tick_frequency_hz:
            return None
        return TimeSyncManager.tick_to_us(self.camera_ts0, self.tick_frequency_hz)


@dataclass(frozen=True)
class SessionTimeSync:
    """Session-wide time sync snapshot (no PTP)."""

    strategy: str
    host_t0_monotonic: float
    host_t0_wall: str
    timestamp_reset_on_session: bool
    cross_camera_skew_tolerance_ms: int
    anchors: tuple[CameraTimeAnchor, ...]
    max_cross_camera_skew_us: int | None = None

    def host_elapsed_us(self, t_monotonic: float | None = None) -> int:
        """Microseconds since session host_t0."""
        t = time.monotonic() if t_monotonic is None else t_monotonic
        return int((t - self.host_t0_monotonic) * 1_000_000)

    def monotonic_us_to_epoch(self, mono_us: int) -> float:
        """Map absolute ``time.monotonic()*1e6`` to POSIX epoch via session wall anchor."""
        t0 = datetime.fromisoformat(self.host_t0_wall)
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        return t0.timestamp() + (mono_us / 1_000_000 - self.host_t0_monotonic)

    def to_dict(self) -> dict:
        """JSON-serializable report block."""
        return {
            "strategy": self.strategy,
            "host_t0_wall": self.host_t0_wall,
            "timestamp_reset_on_session": self.timestamp_reset_on_session,
            "cross_camera_skew_tolerance_ms": self.cross_camera_skew_tolerance_ms,
            "max_cross_camera_skew_us": self.max_cross_camera_skew_us,
            "cameras": [
                {
                    "camera_index": a.camera_index,
                    "ip": a.ip,
                    "camera_ts0": a.camera_ts0,
                    "camera_ts0_us": a.camera_ts0_us,
                    "tick_frequency_hz": a.tick_frequency_hz,
                    "reset_performed": a.reset_performed,
                    "open_error": a.open_error,
                    "reset_error": a.reset_error,
                }
                for a in self.anchors
            ],
        }


class TimeSyncManager:
    """Establish host monotonic + per-camera timestamp anchors for a session."""

    STRATEGY = "host_clock_sync"

    @staticmethod
    def tick_to_us(ticks: int, tick_frequency_hz: int) -> int:
        """Convert camera tick counter to microseconds."""
        if tick_frequency_hz <= 0:
            return 0
        return ticks * 1_000_000 // tick_frequency_hz

    @staticmethod
    def _anchor_from_report(
        endpoint: CameraEndpoint, report: TimestampCameraReport
    ) -> CameraTimeAnchor:
        ts0 = (
            report.timestamp_after
            if report.reset_performed
            else report.timestamp_before
        )
        return CameraTimeAnchor(
            camera_index=endpoint.index,
            ip=endpoint.ip,
            camera_ts0=ts0,
            tick_frequency_hz=report.tick_frequency_hz,
            reset_performed=report.reset_performed,
            open_error=report.open_error,
            reset_error=report.reset_error,
        )

    @staticmethod
    def _max_cross_camera_skew_us(anchors: tuple[CameraTimeAnchor, ...]) -> int | None:
        """Max spread of camera_ts0_us across channels (informational after sequential reset)."""
        us_vals = [a.camera_ts0_us for a in anchors if a.camera_ts0_us is not None]
        if len(us_vals) < 2:
            return None
        return max(us_vals) - min(us_vals)

    def begin_session(
        self,
        endpoints: tuple[CameraEndpoint, ...],
        *,
        timestamp_reset: bool = True,
        cross_camera_skew_tolerance_ms: int = 50,
    ) -> SessionTimeSync:
        """Reset camera counters (optional), latch ts0, record host monotonic t0."""
        host_t0 = time.monotonic()
        host_wall = datetime.now(timezone.utc).isoformat()

        if timestamp_reset:
            reports = reset_all_timestamps(endpoints)
        else:
            reports = [probe_timestamp_readonly(ep) for ep in endpoints]

        anchors = tuple(
            self._anchor_from_report(ep, r) for ep, r in zip(endpoints, reports)
        )
        skew_us = self._max_cross_camera_skew_us(anchors)

        return SessionTimeSync(
            strategy=self.STRATEGY,
            host_t0_monotonic=host_t0,
            host_t0_wall=host_wall,
            timestamp_reset_on_session=timestamp_reset,
            cross_camera_skew_tolerance_ms=cross_camera_skew_tolerance_ms,
            anchors=anchors,
            max_cross_camera_skew_us=skew_us,
        )
