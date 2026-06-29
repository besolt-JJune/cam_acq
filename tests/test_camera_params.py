"""Runtime camera parameter helpers (no hardware)."""

from __future__ import annotations

from typing import Any

from cam_acq.camera.param_store import RuntimeParamStore
from cam_acq.camera.params import (
    FIELD_ACQUISITION_FRAME_RATE,
    FIELD_EXPOSURE_AUTO,
    FIELD_EXPOSURE_TIME_US,
    FIELD_GAIN,
    FIELD_GAIN_AUTO,
    FIELD_GAMMA,
    FIELD_GAMMA_MODE,
    apply_camera_params,
    patch_to_param_dict,
    read_camera_params,
)


class _FakeFeature:
    def __init__(self, name: str, *, readable: bool = True, writable: bool = True) -> None:
        self.feature_name = name
        self._readable = readable
        self._writable = writable
        self.value: Any = None
        self._range: dict[str, int] = {}

    def is_readable(self) -> bool:
        return self._readable

    def is_writable(self) -> bool:
        return self._writable

    def get_range(self) -> dict[str, int]:
        return dict(self._range)

    def get(self) -> tuple[int, str]:
        inv = {v: k for k, v in self._range.items()}
        return int(self.value), inv[int(self.value)]

    def set(self, value: Any) -> None:
        self.value = value


class _FakeFloatFeature:
    def __init__(self, name: str, value: float = 0.0) -> None:
        self.feature_name = name
        self.value = value

    def is_readable(self) -> bool:
        return True

    def is_writable(self) -> bool:
        return True

    def get(self) -> float:
        return float(self.value)

    def set(self, value: float) -> None:
        self.value = float(value)


def _fake_cam() -> Any:
  cam = type("Cam", (), {})()
  cam.ExposureAuto = _FakeFeature("ExposureAuto")
  cam.ExposureAuto._range = {"Off": 0, "Continuous": 1, "Once": 2}
  cam.ExposureAuto.value = 0
  cam.GainAuto = _FakeFeature("GainAuto")
  cam.GainAuto._range = {"Off": 0, "Continuous": 1, "Once": 2}
  cam.GainAuto.value = 0
  cam.GammaMode = _FakeFeature("GammaMode")
  cam.GammaMode._range = {"sRGB": 0, "User": 1}
  cam.GammaMode.value = 1
  cam.ExposureTime = _FakeFloatFeature("ExposureTime", 10000.0)
  cam.Gain = _FakeFloatFeature("Gain", 5.0)
  cam.AcquisitionFrameRate = _FakeFloatFeature("AcquisitionFrameRate", 23.0)
  cam.AcquisitionFrameRateMode = _FakeFeature("AcquisitionFrameRateMode")
  cam.AcquisitionFrameRateMode._range = {"Off": 0, "On": 1}
  cam.AcquisitionFrameRateMode.value = 0
  cam.GammaEnable = type("B", (), {"is_writable": lambda self: True, "set": lambda self, v: None})()
  cam.Gamma = _FakeFloatFeature("Gamma", 1.0)
  return cam


def test_patch_to_param_dict_ignores_none():
    body = patch_to_param_dict(
        {"exposure_time_us": 5000.0, "gain": None, "unknown": 1}
    )
    assert body == {FIELD_EXPOSURE_TIME_US: 5000.0}


def test_apply_and_read_roundtrip():
    cam = _fake_cam()
    apply_camera_params(
        cam,
        {
            FIELD_EXPOSURE_AUTO: "Off",
            FIELD_EXPOSURE_TIME_US: 8000.0,
            FIELD_GAIN_AUTO: "Continuous",
            FIELD_GAIN: 12.0,
            FIELD_ACQUISITION_FRAME_RATE: 20.0,
            FIELD_GAMMA_MODE: "User",
            FIELD_GAMMA: 1.2,
        },
    )
    assert cam.ExposureTime.value == 8000.0
    assert cam.Gain.value == 12.0
    assert cam.AcquisitionFrameRate.value == 20.0
    assert cam.AcquisitionFrameRateMode.value == 1
    assert cam.Gamma.value == 1.2
    snap = read_camera_params(cam)
    assert snap[FIELD_EXPOSURE_TIME_US] == 8000.0
    assert snap[FIELD_GAIN] == 12.0


def test_runtime_store_apply_only_on_request():
    store = RuntimeParamStore((0,))
    cam = _fake_cam()
    store.on_camera_open(cam, 0)
    assert store.apply_if_requested(cam, 0) is False
    store.queue_update(0, {FIELD_GAIN: 7.5})
    assert store.apply_if_requested(cam, 0) is True
    assert cam.Gain.value == 7.5
    assert store.apply_if_requested(cam, 0) is False
    snap = store.snapshot(0)
    assert snap is not None
    assert snap["apply_pending"] is False
    assert snap[FIELD_GAIN] == 7.5


if __name__ == "__main__":
    test_patch_to_param_dict_ignores_none()
    test_apply_and_read_roundtrip()
    test_runtime_store_apply_only_on_request()
    print("ok")
