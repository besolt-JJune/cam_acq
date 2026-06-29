"""GenICam exposure, gain, fps, and gamma read/apply via gxipy (grab-thread only)."""

from __future__ import annotations

from typing import Any

from gxipy.gxidef import GxSwitchEntry

FIELD_EXPOSURE_TIME_US = "exposure_time_us"
FIELD_EXPOSURE_AUTO = "exposure_auto"
FIELD_ACQUISITION_FRAME_RATE = "acquisition_frame_rate"
FIELD_GAIN = "gain"
FIELD_GAIN_AUTO = "gain_auto"
FIELD_GAMMA_MODE = "gamma_mode"
FIELD_GAMMA = "gamma"

ALL_PARAM_FIELDS = (
    FIELD_EXPOSURE_TIME_US,
    FIELD_EXPOSURE_AUTO,
    FIELD_ACQUISITION_FRAME_RATE,
    FIELD_GAIN,
    FIELD_GAIN_AUTO,
    FIELD_GAMMA_MODE,
    FIELD_GAMMA,
)


def _enum_label(feature: Any) -> str | None:
    """Return symbolic enum label when the feature is readable."""
    if not feature.is_readable():
        return None
    _, label = feature.get()
    return str(label)


def _float_value(feature: Any) -> float | None:
    """Return float feature value when readable."""
    if not feature.is_readable():
        return None
    return float(feature.get())


def read_enum_options(cam: Any) -> dict[str, list[str]]:
    """Symbolic labels allowed for enum GenICam features (for dashboard selects)."""
    out: dict[str, list[str]] = {}
    for field, attr in (
        (FIELD_EXPOSURE_AUTO, "ExposureAuto"),
        (FIELD_GAIN_AUTO, "GainAuto"),
        (FIELD_GAMMA_MODE, "GammaMode"),
    ):
        feature = getattr(cam, attr, None)
        if feature is None or not feature.is_readable():
            continue
        try:
            out[field] = [str(name) for name in feature.get_range().keys()]
        except Exception:
            continue
    return out


def read_camera_params(cam: Any) -> dict[str, float | str | None]:
    """Snapshot current GenICam values for API responses."""
    return {
        FIELD_EXPOSURE_TIME_US: _float_value(cam.ExposureTime),
        FIELD_EXPOSURE_AUTO: _enum_label(cam.ExposureAuto),
        FIELD_ACQUISITION_FRAME_RATE: _float_value(cam.AcquisitionFrameRate),
        FIELD_GAIN: _float_value(cam.Gain),
        FIELD_GAIN_AUTO: _enum_label(cam.GainAuto),
        FIELD_GAMMA_MODE: _enum_label(cam.GammaMode),
        FIELD_GAMMA: _float_value(cam.Gamma),
    }


def _resolve_enum(feature: Any, label: str) -> int:
    """Map a symbolic enum name (case-insensitive) to the device integer value."""
    symbolic = label.strip()
    range_dict = feature.get_range()
    for name, value in range_dict.items():
        if str(name).lower() == symbolic.lower():
            return int(value)
    raise ValueError(
        f"unknown {feature.feature_name} value {label!r}; allowed: {list(range_dict)}"
    )


def apply_camera_params(cam: Any, values: dict[str, Any]) -> None:
    """Apply parameter updates on the open camera handle (must run on grab thread)."""
    if FIELD_EXPOSURE_AUTO in values and cam.ExposureAuto.is_writable():
        cam.ExposureAuto.set(_resolve_enum(cam.ExposureAuto, str(values[FIELD_EXPOSURE_AUTO])))

    if FIELD_GAIN_AUTO in values and cam.GainAuto.is_writable():
        cam.GainAuto.set(_resolve_enum(cam.GainAuto, str(values[FIELD_GAIN_AUTO])))

    if FIELD_EXPOSURE_TIME_US in values and cam.ExposureTime.is_writable():
        cam.ExposureTime.set(float(values[FIELD_EXPOSURE_TIME_US]))

    if FIELD_GAIN in values and cam.Gain.is_writable():
        cam.Gain.set(float(values[FIELD_GAIN]))

    if FIELD_ACQUISITION_FRAME_RATE in values:
        mode = getattr(cam, "AcquisitionFrameRateMode", None)
        if mode is not None and mode.is_writable():
            mode.set(GxSwitchEntry.ON)
        if cam.AcquisitionFrameRate.is_writable():
            cam.AcquisitionFrameRate.set(float(values[FIELD_ACQUISITION_FRAME_RATE]))

    if FIELD_GAMMA_MODE in values and cam.GammaMode.is_writable():
        cam.GammaMode.set(_resolve_enum(cam.GammaMode, str(values[FIELD_GAMMA_MODE])))

    if FIELD_GAMMA in values:
        enable = getattr(cam, "GammaEnable", None)
        if enable is not None and enable.is_writable():
            enable.set(True)
        if cam.Gamma.is_writable():
            cam.Gamma.set(float(values[FIELD_GAMMA]))


def patch_to_param_dict(body: dict[str, Any]) -> dict[str, Any]:
    """Keep only supported keys with non-None values from a PATCH body."""
    out: dict[str, Any] = {}
    for key in ALL_PARAM_FIELDS:
        if key in body and body[key] is not None:
            out[key] = body[key]
    return out
