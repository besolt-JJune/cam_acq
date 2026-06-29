"""Phase 5 monitoring self-check (no camera/GPU/httpx)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from cam_acq.camera.frame import DebayerBackend
from cam_acq.config import CameraEndpoint, Settings
from cam_acq.detection.events import RecordingTrigger
from cam_acq.monitoring.collector import DashboardCollector
from cam_acq.monitoring.pipeline_hooks import PipelineHooks
from cam_acq.monitoring.thumbnails import ThumbnailStore
from cam_acq.recording.controller import RecordingController
from cam_acq.recording.storage import StorageManager


def _settings() -> Settings:
    return Settings(
        num_cameras=1,
        cameras=(CameraEndpoint(0, "10.0.0.1"),),
        log_path=Path("./logs"),
        healthcheck_output_dir=Path("./logs"),
        pixel_format="BayerRG8",
        bayer_format="RGGB",
        camera_width=0,
        camera_height=0,
        timestamp_reset_on_session=True,
        cross_camera_skew_tolerance_ms=50,
        gige_recovery_retry_sec=2.0,
        gige_recovery_max_attempts=5,
        gige_feature_backup_dir=Path("./healthcheck"),
        socket_buffer_min_bytes=10_485_760,
        resize_width=960,
        resize_height=540,
        detection_model_path=Path("models/x.engine"),
        detection_onnx_path=Path("models/x.onnx"),
        detection_confidence=0.5,
        detection_input_size=640,
        recording_buffer_sec=10.0,
        recording_split_interval_sec=60.0,
        encoding_codec="H265",
        encoding_bitrate_mbps=12.0,
        storage_path=Path("./recordings"),
        storage_path_sub=Path("./recordings"),
        storage_management="FIFO_DELETE",
        storage_full_percentage=90,
        debayer_backend=DebayerBackend.CPU_SDK,
        gpu_id=0,
        deepstream_yolo_lib=Path("lib.so"),
        monitoring_web_port=8080,
        ui_max_display_fps=15,
        system_metrics_poll_sec=2.0,
        cpu_warn_percent=85,
        ram_warn_percent=85,
        gpu_util_warn_percent=90,
        gpu_temp_warn_c=80,
        gpu_temp_critical_c=90,
    )


def test_thumbnail_store_jpeg():
    store = ThumbnailStore()
    rgb = np.zeros((54, 96, 3), dtype=np.uint8)
    rgb[10:20, 10:30, 1] = 255
    store.update_rgb(0, rgb)
    assert store.get_jpeg(0) is not None
    assert store.get_jpeg(0)[:2] == b"\xff\xd8"


def test_recording_trigger_requires_pipeline():
    col = DashboardCollector(_settings())
    try:
        col.manual_recording_trigger()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_recording_trigger_ok():
    settings = _settings()
    storage = StorageManager(settings.storage_path, settings.storage_path_sub)
    ctrl = RecordingController(
        storage=storage,
        camera_indices=(0,),
        buffer_sec=10.0,
        split_interval_sec=60.0,
        pixel_format="BayerRG8",
        bayer_format="RGGB",
        codec="H265",
        bitrate_bps=12_000_000,
        gpu_id=0,
    )
    trig = RecordingTrigger(
        buffer_sec=10.0,
        confidence_threshold=0.5,
        camera_indices=(0,),
    )
    hooks = PipelineHooks()
    hooks.bind_recording(ctrl, trigger=trig)
    col = DashboardCollector(settings, hooks=hooks, storage_manager=storage)
    decision = col.manual_recording_start()
    assert decision["source"] == "manual"
    assert ctrl.status_snapshot(manual_active=True)["state"] == "recording"
    body = col.dashboard_payload()
    assert body["recording"].get("manual_elapsed_sec", 0) >= 0


def test_dashboard_features_block():
    col = DashboardCollector(_settings())
    body = col.dashboard_payload()
    assert "features" in body
    assert body["features"]["recording"] is False


if __name__ == "__main__":
    test_thumbnail_store_jpeg()
    test_recording_trigger_requires_pipeline()
    test_recording_trigger_ok()
    test_dashboard_features_block()
    print("ok")
