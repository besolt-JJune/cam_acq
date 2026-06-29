"""Camera internal timestamp probe and TimestampReset via gxipy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cam_acq.camera.device import close_camera, open_camera_by_ip
from cam_acq.config import CameraEndpoint

TIMESTAMP_FEATURES = (
    "TimestampTickFrequency",
    "GevTimestampTickFrequency",
    "TimestampLatch",
    "TimestampLatchValue",
    "TimestampReset",
    "TimestampLatchReset",
    "ChunkTimestamp",
)


@dataclass
class TimestampCameraReport:
    """Timestamp feature probe / reset result for one camera."""

    camera_index: int
    ip: str
    open_error: str | None = None
    implemented: dict[str, bool] = field(default_factory=dict)
    readable: dict[str, bool] = field(default_factory=dict)
    tick_frequency_hz: int | None = None
    timestamp_before: int | None = None
    timestamp_after: int | None = None
    reset_performed: bool = False
    reset_error: str | None = None


def _feature_implemented(cam: Any, fc: Any, name: str) -> bool:
    """Prefer Device shortcut attributes; fall back to FeatureControl."""
    attr = getattr(cam, name, None)
    if attr is not None and hasattr(attr, "is_implemented"):
        return bool(attr.is_implemented())
    return bool(fc.is_implemented(name))


def _feature_readable(cam: Any, fc: Any, name: str) -> bool:
    attr = getattr(cam, name, None)
    if attr is not None and hasattr(attr, "is_readable"):
        return bool(attr.is_readable())
    return bool(fc.is_readable(name))


def _read_tick_frequency(cam: Any, fc: Any) -> int | None:
    for name in ("TimestampTickFrequency", "GevTimestampTickFrequency"):
        if not _feature_readable(cam, fc, name):
            continue
        attr = getattr(cam, name, None)
        if attr is not None and attr.is_readable():
            return int(attr.get())
        if fc.is_readable(name):
            return int(fc.get_int_feature(name).get())
    return None


def _latch_timestamp(cam: Any, fc: Any) -> int | None:
    """Latch device counter and return TimestampLatchValue."""
    if not _feature_implemented(cam, fc, "TimestampLatch"):
        return None
    if hasattr(cam, "TimestampLatch") and cam.TimestampLatch.is_implemented():
        cam.TimestampLatch.send_command()
    elif fc.is_implemented("TimestampLatch"):
        fc.get_command_feature("TimestampLatch").send_command()
    else:
        return None

    if hasattr(cam, "TimestampLatchValue") and cam.TimestampLatchValue.is_readable():
        return int(cam.TimestampLatchValue.get())
    if fc.is_readable("TimestampLatchValue"):
        return int(fc.get_int_feature("TimestampLatchValue").get())
    return None


def _send_timestamp_reset(cam: Any, fc: Any) -> None:
    """Send TimestampReset command (resets free-running counter, not wall clock)."""
    if hasattr(cam, "TimestampReset") and cam.TimestampReset.is_implemented():
        cam.TimestampReset.send_command()
        return
    if fc.is_implemented("TimestampReset"):
        fc.get_command_feature("TimestampReset").send_command()
        return
    raise RuntimeError("TimestampReset not implemented")


def probe_timestamp_readonly(endpoint: CameraEndpoint) -> TimestampCameraReport:
    """Open camera and report timestamp-related GenICam features."""
    report = TimestampCameraReport(camera_index=endpoint.index, ip=endpoint.ip)
    cam = None
    try:
        cam = open_camera_by_ip(endpoint.ip)
        fc = cam.get_remote_device_feature_control()
        for name in TIMESTAMP_FEATURES:
            report.implemented[name] = _feature_implemented(cam, fc, name)
            report.readable[name] = _feature_readable(cam, fc, name)
        report.tick_frequency_hz = _read_tick_frequency(cam, fc)
        report.timestamp_before = _latch_timestamp(cam, fc)
    except Exception as exc:
        report.open_error = str(exc)
    finally:
        close_camera(cam)
    return report


def reset_camera_timestamp(endpoint: CameraEndpoint) -> TimestampCameraReport:
    """Latch counter, TimestampReset, latch again; record before/after values."""
    report = probe_timestamp_readonly(endpoint)
    if report.open_error:
        return report
    if not report.implemented.get("TimestampReset"):
        report.reset_error = "TimestampReset not implemented"
        return report

    cam = None
    try:
        cam = open_camera_by_ip(endpoint.ip)
        fc = cam.get_remote_device_feature_control()
        report.timestamp_before = _latch_timestamp(cam, fc)
        _send_timestamp_reset(cam, fc)
        report.timestamp_after = _latch_timestamp(cam, fc)
        report.reset_performed = True
    except Exception as exc:
        report.reset_error = str(exc)
    finally:
        close_camera(cam)
    return report


def reset_all_timestamps(
    endpoints: tuple[CameraEndpoint, ...],
) -> list[TimestampCameraReport]:
    """Reset each camera timestamp sequentially (session anchor helper)."""
    return [reset_camera_timestamp(ep) for ep in endpoints]
