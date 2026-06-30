"""Per-camera GigE grab: Bayer ring (recording) and optional resized RGB (detection)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cam_acq.camera.device import close_camera, open_camera_by_ip
from cam_acq.camera.frame import DebayerBackend, BayerFrame, raw_image_to_bayer_frame, raw_image_to_frame
from cam_acq.camera.recovery import (
    OfflineSignal,
    RecoveryStats,
    _safe_stream_off,
    _safe_unregister_offline,
    handle_offline,
    make_feature_backup_path,
    register_offline_handler,
    save_feature_backup,
)
from gxipy.gxidef import GxFrameStatusList, GxSwitchEntry

if TYPE_CHECKING:
    import numpy as np

    from cam_acq.camera.param_store import RuntimeParamStore
    from cam_acq.recording.controller import RecordingController

logger = logging.getLogger(__name__)

# ponytail: get_image(timeout=1000) × N ≈ stall seconds before forced reconnect path
_GRAB_STALL_MISSES = 3


def _configure_continuous(cam: Any) -> None:
    cam.TriggerMode.set(GxSwitchEntry.OFF)


def run_camera_grab_loop(
    *,
    ip: str,
    camera_index: int,
    stop_at: float,
    controller: RecordingController | None = None,
    on_rgb_frame: Callable[[np.ndarray], None] | None = None,
    on_bayer_frame: Callable[[BayerFrame], None] | None = None,
    resize_w: int = 0,
    resize_h: int = 0,
    debayer_backend: DebayerBackend = DebayerBackend.CPU_SDK,
    bayer_format: str = "RGGB",
    param_store: RuntimeParamStore | None = None,
    on_camera_open: Callable[[Any, int], None] | None = None,
    errors: list[str] | None = None,
) -> None:
    """Grab from one camera; push Bayer to ring and/or deliver RGB or Bayer for detection."""
    import time

    cam = None
    try:
        cam = open_camera_by_ip(ip)
        _configure_continuous(cam)
        if on_camera_open is not None:
            on_camera_open(cam, camera_index)
        if param_store is not None:
            param_store.on_camera_open(cam, camera_index)
        cam.stream_on()
        while time.monotonic() < stop_at:
            if param_store is not None:
                param_store.apply_if_requested(cam, camera_index)
            raw = cam.data_stream[0].get_image(timeout=1000)
            if raw is None:
                continue
            if raw.get_status() != GxFrameStatusList.SUCCESS:
                continue
            if controller is not None:
                controller.push_raw(camera_index, raw)
            if on_bayer_frame is not None:
                bayer = raw_image_to_bayer_frame(raw, bayer_format=bayer_format)
                if bayer is not None:
                    on_bayer_frame(bayer)
            elif on_rgb_frame is not None:
                rgb = raw_image_to_frame(
                    raw,
                    resize_w,
                    resize_h,
                    backend=debayer_backend,
                )
                if rgb is not None:
                    on_rgb_frame(rgb)
    except Exception as exc:
        if errors is not None:
            errors.append(f"cam{camera_index}: {exc}")
        raise
    finally:
        if cam is not None:
            try:
                cam.stream_off()
            except Exception:
                pass
        close_camera(cam)


def run_camera_grab_loop_with_recovery(
    *,
    ip: str,
    camera_index: int,
    stop_at: float,
    feature_backup_dir: Path,
    recovery: RecoveryStats,
    controller: RecordingController | None = None,
    on_rgb_frame: Callable[[np.ndarray], None] | None = None,
    on_bayer_frame: Callable[[BayerFrame], None] | None = None,
    resize_w: int = 0,
    resize_h: int = 0,
    debayer_backend: DebayerBackend = DebayerBackend.CPU_SDK,
    bayer_format: str = "RGGB",
    param_store: RuntimeParamStore | None = None,
    on_camera_open: Callable[[Any, int], None] | None = None,
    on_connection_offline: Callable[[bool], None] | None = None,
    on_recovery_cycle: Callable[[], None] | None = None,
    retry_interval_sec: float = 2.0,
    max_attempts: int = 5,
    errors: list[str] | None = None,
) -> None:
    """Grab with GigE offline callback; notify recording before reconnect."""
    import time

    cam = None
    offline = OfflineSignal()
    backup = make_feature_backup_path(feature_backup_dir, camera_index)
    try:
        cam = open_camera_by_ip(ip)
        _configure_continuous(cam)
        save_feature_backup(cam, backup)
        if on_camera_open is not None:
            on_camera_open(cam, camera_index)
        if param_store is not None:
            param_store.on_camera_open(cam, camera_index)
        register_offline_handler(cam, offline)
        cam.stream_on()
        consecutive_miss = 0
        while time.monotonic() < stop_at:

            def _process_offline() -> bool:
                """Run disconnect hooks + IP reconnect; return False if reconnect failed."""
                nonlocal cam, consecutive_miss
                at_us = int(time.monotonic() * 1_000_000)
                offline_index = recovery.offline_events + 1
                if on_connection_offline is not None:
                    on_connection_offline(True)
                if controller is not None:
                    controller.on_camera_offline(
                        camera_index,
                        at_host_us=at_us,
                        offline_event_index=offline_index,
                    )
                cam = handle_offline(
                    cam,
                    ip,
                    offline,
                    recovery,
                    feature_backup=backup,
                    retry_interval_sec=retry_interval_sec,
                    max_attempts=max_attempts,
                )
                consecutive_miss = 0
                if cam is None:
                    if errors is not None:
                        errors.append(
                            f"cam{camera_index}: {recovery.last_reconnect_error}"
                        )
                    return False
                if param_store is not None:
                    param_store.requeue(camera_index)
                reconnect_us = int(time.monotonic() * 1_000_000)
                if controller is not None:
                    controller.on_camera_reconnect(camera_index, at_host_us=reconnect_us)
                if on_connection_offline is not None:
                    on_connection_offline(False)
                if on_recovery_cycle is not None:
                    on_recovery_cycle()
                logger.info(
                    "gige recovery cam=%s offline_events=%s reconnect_success=%s",
                    camera_index,
                    recovery.offline_events,
                    recovery.reconnect_success,
                )
                return True

            if offline.is_set():
                if not _process_offline():
                    break

            if param_store is not None:
                param_store.apply_if_requested(cam, camera_index)
            raw = cam.data_stream[0].get_image(timeout=1000)
            if raw is None or raw.get_status() != GxFrameStatusList.SUCCESS:
                consecutive_miss += 1
                if consecutive_miss >= _GRAB_STALL_MISSES and not offline.is_set():
                    logger.warning(
                        "grab stall cam=%s misses=%s; forcing offline recovery",
                        camera_index,
                        consecutive_miss,
                    )
                    offline.set()
                continue
            consecutive_miss = 0
            if controller is not None:
                controller.push_raw(camera_index, raw)
            if on_bayer_frame is not None:
                bayer = raw_image_to_bayer_frame(raw, bayer_format=bayer_format)
                if bayer is not None:
                    on_bayer_frame(bayer)
            elif on_rgb_frame is not None:
                rgb = raw_image_to_frame(
                    raw,
                    resize_w,
                    resize_h,
                    backend=debayer_backend,
                )
                if rgb is not None:
                    on_rgb_frame(rgb)
    except Exception as exc:
        if errors is not None:
            errors.append(f"cam{camera_index}: {exc}")
        raise
    finally:
        if cam is not None:
            _safe_stream_off(cam)
            _safe_unregister_offline(cam)
        close_camera(cam)
