"""GigE offline detection and reconnect (gxipy offline callback + feature backup)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cam_acq.camera.device import close_camera, get_device_manager, open_camera_by_ip
from gxipy.gxidef import GxSwitchEntry

logger = logging.getLogger(__name__)


@dataclass
class RecoveryStats:
    """Per-camera GigE recovery counters."""

    offline_events: int = 0
    reconnect_success: int = 0
    reconnect_failed: int = 0
    last_reconnect_error: str | None = None


class OfflineSignal:
    """Thread-safe offline flag for SDK callback (may run on native thread)."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def clear(self) -> None:
        self._event.clear()


def _configure_continuous(cam: Any) -> None:
    cam.TriggerMode.set(GxSwitchEntry.OFF)


def save_feature_backup(cam: Any, path: Path) -> bool:
    """Save GenICam user set for reload after reconnect."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cam.get_remote_device_feature_control().feature_save(str(path))
        return True
    except Exception as exc:
        logger.warning("feature_save failed path=%s err=%s", path, exc)
        return False


def load_feature_backup(cam: Any, path: Path) -> bool:
    """Restore GenICam user set after reconnect."""
    if not path.is_file():
        return False
    try:
        cam.get_remote_device_feature_control().feature_load(str(path), verify=False)
        return True
    except Exception as exc:
        logger.warning("feature_load failed path=%s err=%s", path, exc)
        return False


def _safe_stream_off(cam: Any) -> None:
    try:
        cam.stream_off()
    except Exception:
        pass


def _safe_unregister_offline(cam: Any) -> None:
    try:
        cam.unregister_device_offline_callback()
    except Exception:
        pass


def reopen_camera_stream(
    ip: str,
    signal: OfflineSignal,
    stats: RecoveryStats,
    *,
    feature_backup: Path | None,
    retry_interval_sec: float = 2.0,
    max_attempts: int = 5,
) -> Any | None:
    """Open camera by IP, register offline callback, stream_on (no teardown)."""
    last_err: Exception | None = None
    limit = max_attempts if max_attempts > 0 else None
    attempt = 0
    while limit is None or attempt < limit:
        attempt += 1
        try:
            get_device_manager(refresh=True)
            cam = open_camera_by_ip(ip)
            _configure_continuous(cam)
            if feature_backup is not None:
                load_feature_backup(cam, feature_backup)
            register_offline_handler(cam, signal)
            cam.stream_on()
            stats.reconnect_success += 1
            stats.last_reconnect_error = None
            return cam
        except Exception as exc:
            last_err = exc
            logger.warning(
                "reconnect attempt %s%s ip=%s err=%s",
                attempt,
                f"/{max_attempts}" if limit is not None else "",
                ip,
                exc,
            )
            time.sleep(retry_interval_sec)
    stats.reconnect_failed += 1
    stats.last_reconnect_error = str(last_err) if last_err else "reconnect failed"
    return None


def reconnect_camera(
    ip: str,
    *,
    feature_backup: Path | None,
    retry_interval_sec: float = 2.0,
    max_attempts: int = 5,
) -> Any:
    """Close stale handle and reopen by IP; reload feature backup if present."""
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            get_device_manager(refresh=True)
            cam = open_camera_by_ip(ip)
            _configure_continuous(cam)
            if feature_backup is not None:
                load_feature_backup(cam, feature_backup)
            return cam
        except Exception as exc:
            last_err = exc
            logger.warning(
                "reconnect attempt %s/%s ip=%s err=%s",
                attempt,
                max_attempts,
                ip,
                exc,
            )
            time.sleep(retry_interval_sec)
    raise RuntimeError(f"reconnect failed for {ip}") from last_err


def register_offline_handler(cam: Any, signal: OfflineSignal) -> None:
    """Register gxipy offline callback (must be plain function, not bound method)."""

    def _on_offline() -> None:
        signal.set()

    cam.register_device_offline_callback(_on_offline)
    cam._cam_acq_offline_callback = _on_offline  # ponytail: prevent GC of callback


def handle_offline(
    cam: Any | None,
    ip: str,
    signal: OfflineSignal,
    stats: RecoveryStats,
    *,
    feature_backup: Path | None,
    retry_interval_sec: float,
    max_attempts: int,
) -> Any | None:
    """Process offline: tear down cam, reconnect, return new handle or None."""
    stats.offline_events += 1
    signal.clear()
    if cam is not None:
        _safe_stream_off(cam)
        _safe_unregister_offline(cam)
        close_camera(cam)

    new_cam = reopen_camera_stream(
        ip,
        signal,
        stats,
        feature_backup=feature_backup,
        retry_interval_sec=retry_interval_sec,
        max_attempts=max_attempts,
    )
    if new_cam is None:
        logger.error(
            "offline recovery failed ip=%s err=%s",
            ip,
            stats.last_reconnect_error,
        )
    return new_cam


def make_feature_backup_path(base_dir: Path, camera_index: int) -> Path:
    """Per-camera feature backup file path."""
    return base_dir / f"cam{camera_index}_feature.bin"
