"""Optional live pipeline bindings for dashboard metrics (grab, detection, recording)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cam_acq.camera.grab import GrabStats
    from cam_acq.camera.param_store import RuntimeParamStore
    from cam_acq.camera.timesync import SessionTimeSync
    from cam_acq.detection.events import DetectionFrameEvent, RecordingTrigger
    from cam_acq.recording.controller import RecordingController


class PipelineHooks:
    """Thread-safe registry updated by grab/YOLO/recording loops."""

    def __init__(self, *, param_store: RuntimeParamStore | None = None) -> None:
        from cam_acq.monitoring.thumbnails import ThumbnailStore

        self._lock = threading.Lock()
        self._grab: dict[int, GrabStats] = {}
        self._detection: dict[int, DetectionFrameEvent] = {}
        self._recording: RecordingController | None = None
        self._trigger: RecordingTrigger | None = None
        self._time_sync: SessionTimeSync | None = None
        self._param_store = param_store
        self._thumbnails = ThumbnailStore()

    @property
    def thumbnails(self) -> ThumbnailStore:
        """Latest resize JPEG frames for MJPEG streams."""
        return self._thumbnails

    @property
    def param_store(self) -> RuntimeParamStore | None:
        """Runtime GenICam parameter queue shared with grab threads."""
        return self._param_store

    def bind_param_store(self, store: RuntimeParamStore | None) -> None:
        """Attach or replace the runtime parameter store."""
        with self._lock:
            self._param_store = store

    def set_grab_stats(self, stats: GrabStats) -> None:
        """Replace grab stats for one camera (call from grab thread each tick or on change)."""
        with self._lock:
            self._grab[stats.camera_index] = stats

    def set_detection(self, event: DetectionFrameEvent) -> None:
        """Store latest detection frame event per camera."""
        with self._lock:
            self._detection[event.camera_index] = event

    def bind_recording(
        self,
        controller: RecordingController | None,
        *,
        trigger: RecordingTrigger | None = None,
    ) -> None:
        """Attach recording controller and optional auto-trigger state."""
        with self._lock:
            self._recording = controller
            self._trigger = trigger

    def bind_time_sync(self, session: SessionTimeSync | None) -> None:
        """Attach session time-sync snapshot."""
        with self._lock:
            self._time_sync = session

    def snapshot(self) -> tuple[
        dict[int, GrabStats],
        dict[int, DetectionFrameEvent],
        RecordingController | None,
        RecordingTrigger | None,
        SessionTimeSync | None,
    ]:
        """Copy current hook state for collector reads."""
        with self._lock:
            return (
                dict(self._grab),
                dict(self._detection),
                self._recording,
                self._trigger,
                self._time_sync,
            )
