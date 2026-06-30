"""Open Galaxy cameras via gxipy (work around SDK initialization quirks)."""

from __future__ import annotations

import threading
from typing import Any

import gxipy as gx
from gxipy.gxidef import GxAccessMode

_dm: Any | None = None
_dm_lock = threading.Lock()


def _ensure_device_manager(*, refresh: bool) -> Any:
    """Caller must hold _dm_lock."""
    global _dm
    if _dm is None:
        _dm = gx.DeviceManager()
    if refresh:
        _dm.update_device_list()
    return _dm


def get_device_manager(*, refresh: bool = True) -> Any:
    """Return process-wide DeviceManager (gxipy C API is single-init)."""
    with _dm_lock:
        return _ensure_device_manager(refresh=refresh)


def open_camera_by_ip(
    ip: str,
    access_mode: int = GxAccessMode.CONTROL,
    *,
    refresh: bool | None = None,
) -> Any:
    """Open GEV camera by IP after refreshing the device/interface list.

    gxipy's open_device_by_ip does not call update_device_list(); without it
    __interface_info_list stays empty and __create_device raises IndexError.

    Uses one shared DeviceManager. ``refresh`` defaults to True only on the
    first init; parallel grab threads must not refresh while another camera
    is open (gx_update_device_list is not re-entrant).
    """
    with _dm_lock:
        if refresh is None:
            refresh = _dm is None
        dm = _ensure_device_manager(refresh=refresh)
        cam = dm.open_device_by_ip(ip, access_mode)
    cam._cam_acq_device_manager = dm
    return cam


def close_camera(cam: Any) -> None:
    """Close camera and release pinned DeviceManager."""
    if cam is None:
        return
    try:
        cam.close_device()
    except Exception:
        pass
    finally:
        if hasattr(cam, "_cam_acq_device_manager"):
            cam._cam_acq_device_manager = None
