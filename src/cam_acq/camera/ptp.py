"""PTP GenICam feature probe via gxipy FeatureControl."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from cam_acq.camera.device import close_camera, open_camera_by_ip

from cam_acq.config import CameraEndpoint

PTP_FEATURES = (
    "PtpEnable",
    "PtpStatus",
    "PtpOffsetFromMaster",
    "PtpDataSetLatch",
    "GevSupportedOptionSelector",
    "GevSupportedOption",
)


@dataclass
class PtpCameraReport:
    """PTP feature read result for one camera."""

    camera_index: int
    ip: str
    open_error: str | None = None
    implemented: dict[str, bool] = field(default_factory=dict)
    readable: dict[str, bool] = field(default_factory=dict)
    ptp_hw_supported: bool | None = None
    ptp_enable_set: bool | None = None
    ptp_status: str | None = None
    ptp_offset_from_master: int | None = None
    poll_seconds: float = 0.0


def _enum_symbolic(fc: Any, name: str) -> str | None:
    if not fc.is_readable(name):
        return None
    val = fc.get_enum_feature(name).get()
    if isinstance(val, tuple):
        return val[1]
    return str(val) if val is not None else None


def _ptp_hw_supported(fc: Any) -> bool | None:
    if not fc.is_implemented("GevSupportedOptionSelector"):
        return None
    sel = fc.get_enum_feature("GevSupportedOptionSelector")
    if not fc.is_implemented("GevSupportedOption"):
        return None
    try:
        sel.set("Ptp")
        return bool(fc.get_bool_feature("GevSupportedOption").get())
    except Exception:
        return False


def probe_ptp_readonly(endpoint: CameraEndpoint) -> PtpCameraReport:
    """Open camera and report which PTP-related features exist."""
    report = PtpCameraReport(camera_index=endpoint.index, ip=endpoint.ip)
    cam = None
    try:
        cam = open_camera_by_ip(endpoint.ip)
        fc = cam.get_remote_device_feature_control()
        for name in PTP_FEATURES:
            report.implemented[name] = fc.is_implemented(name)
            report.readable[name] = fc.is_readable(name)
        report.ptp_hw_supported = _ptp_hw_supported(fc)
    except Exception as exc:
        report.open_error = str(exc)
    finally:
        close_camera(cam)
    return report


def probe_ptp_enable_and_poll(
    endpoint: CameraEndpoint,
    timeout_sec: float = 30.0,
    poll_interval_sec: float = 2.0,
) -> PtpCameraReport:
    """Set PtpEnable=true and poll PtpStatus / PtpOffsetFromMaster."""
    report = probe_ptp_readonly(endpoint)
    if report.open_error:
        return report

    cam = None
    t0 = time.monotonic()
    try:
        cam = open_camera_by_ip(endpoint.ip)
        fc = cam.get_remote_device_feature_control()
        if fc.is_implemented("PtpEnable") and fc.is_writable("PtpEnable"):
            fc.get_bool_feature("PtpEnable").set(True)
            report.ptp_enable_set = True
        else:
            report.ptp_enable_set = False
            return report

        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            report.ptp_status = _enum_symbolic(fc, "PtpStatus")
            if fc.is_implemented("PtpDataSetLatch"):
                fc.get_command_feature("PtpDataSetLatch").send_command()
            if fc.is_readable("PtpOffsetFromMaster"):
                report.ptp_offset_from_master = fc.get_int_feature(
                    "PtpOffsetFromMaster"
                ).get()
            if report.ptp_status in ("Master", "Slave"):
                break
            time.sleep(poll_interval_sec)
        report.poll_seconds = time.monotonic() - t0
    except Exception as exc:
        report.open_error = str(exc)
    finally:
        close_camera(cam)
    return report
