"""Thread-safe runtime camera parameter queue (API thread → grab thread)."""

from __future__ import annotations

import threading
from typing import Any

from cam_acq.camera.params import ALL_PARAM_FIELDS, apply_camera_params, read_camera_params


class RuntimeParamStore:
    """Queue parameter changes from REST/UI; apply on grab thread only when requested."""

    def __init__(self, camera_indices: tuple[int, ...]) -> None:
        self._indices = frozenset(camera_indices)
        self._lock = threading.Lock()
        self._desired: dict[int, dict[str, Any]] = {}
        self._current: dict[int, dict[str, Any]] = {}
        self._pending: dict[int, bool] = {i: False for i in camera_indices}
        self._last_error: dict[int, str | None] = {i: None for i in camera_indices}
        self._apply_events: dict[int, threading.Event] = {
            i: threading.Event() for i in camera_indices
        }

    def is_configured(self, camera_index: int) -> bool:
        """True when camera_index is in the configured set."""
        return camera_index in self._indices

    def on_camera_open(self, cam: Any, camera_index: int) -> None:
        """Seed desired/current from device when a grab loop opens the camera."""
        if camera_index not in self._indices:
            return
        snapshot = read_camera_params(cam)
        with self._lock:
            if camera_index not in self._desired:
                self._desired[camera_index] = dict(snapshot)
            self._current[camera_index] = dict(snapshot)
            self._last_error[camera_index] = None

    def queue_update(self, camera_index: int, updates: dict[str, Any]) -> None:
        """Merge PATCH fields and signal grab thread to apply once (not every frame)."""
        if camera_index not in self._indices:
            raise KeyError(f"camera_index {camera_index} not configured")
        if not updates:
            return
        with self._lock:
            desired = self._desired.setdefault(camera_index, {})
            for key in ALL_PARAM_FIELDS:
                if key in updates:
                    desired[key] = updates[key]
            self._pending[camera_index] = True
            self._last_error[camera_index] = None
        self._apply_events[camera_index].set()

    def requeue(self, camera_index: int) -> None:
        """Re-apply desired state after GigE reconnect (feature backup may reset device)."""
        if camera_index not in self._indices:
            return
        with self._lock:
            if camera_index not in self._desired:
                return
            self._pending[camera_index] = True
        self._apply_events[camera_index].set()

    def apply_if_requested(self, cam: Any, camera_index: int) -> bool:
        """Apply pending params on grab thread when PATCH/requeue signaled; else no-op."""
        if camera_index not in self._indices:
            return False
        if not self._apply_events[camera_index].is_set():
            return False
        self._apply_events[camera_index].clear()

        with self._lock:
            if not self._pending.get(camera_index):
                return False
            desired = dict(self._desired.get(camera_index, {}))
            self._pending[camera_index] = False

        try:
            apply_camera_params(cam, desired)
            snapshot = read_camera_params(cam)
            with self._lock:
                self._current[camera_index] = snapshot
                self._desired[camera_index] = dict(snapshot)
                self._last_error[camera_index] = None
            return True
        except Exception as exc:
            with self._lock:
                self._last_error[camera_index] = str(exc)
                self._pending[camera_index] = True
            self._apply_events[camera_index].set()
            return False

    def snapshot(self, camera_index: int) -> dict[str, Any] | None:
        """API payload for one camera (last applied values + apply state)."""
        if camera_index not in self._indices:
            return None
        with self._lock:
            current = dict(self._current.get(camera_index, {}))
            pending = bool(self._pending.get(camera_index))
            last_error = self._last_error.get(camera_index)
        body: dict[str, Any] = {"camera_index": camera_index, "apply_pending": pending}
        for key in ALL_PARAM_FIELDS:
            body[key] = current.get(key)
        body["last_apply_error"] = last_error
        return body
