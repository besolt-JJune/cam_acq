"""Per-camera GigE grab: Bayer ring (recording) and optional resized RGB (detection)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from cam_acq.camera.device import close_camera, open_camera_by_ip
from cam_acq.camera.frame import DebayerBackend, BayerFrame, raw_image_to_bayer_frame, raw_image_to_frame
from gxipy.gxidef import GxFrameStatusList, GxSwitchEntry

if TYPE_CHECKING:
    import numpy as np

    from cam_acq.camera.param_store import RuntimeParamStore
    from cam_acq.recording.controller import RecordingController


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
    errors: list[str] | None = None,
) -> None:
    """Grab from one camera; push Bayer to ring and/or deliver RGB or Bayer for detection."""
    import time

    cam = None
    try:
        cam = open_camera_by_ip(ip)
        cam.TriggerMode.set(GxSwitchEntry.OFF)
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
