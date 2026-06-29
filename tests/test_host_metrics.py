"""Host metrics and health evaluation self-check (no camera/GPU required)."""

from pathlib import Path

from cam_acq.camera.frame import DebayerBackend
from cam_acq.config import CameraEndpoint, Settings
from cam_acq.monitoring.collector import DashboardCollector
from cam_acq.monitoring.host_metrics import HostMetricsSampler
from cam_acq.monitoring.pipeline_hooks import PipelineHooks
from cam_acq.recording.controller import RecordingController
from cam_acq.recording.storage import StorageManager, disk_usage_at


def _settings(*, cameras: tuple[CameraEndpoint, ...] | None = None) -> Settings:
    cams = cameras or (CameraEndpoint(0, "10.0.0.1"),)
    return Settings(
        num_cameras=len(cams),
        cameras=cams,
        log_path=Path("./logs"),
        healthcheck_output_dir=Path("./logs"),
        pixel_format="BayerRG8",
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


def test_sample_once_has_schema():
    snap = HostMetricsSampler(gpu_index=0, poll_sec=1.0).sample_once()
    d = snap.to_dict()
    assert d["schema_version"] == "1.0"
    assert "collected_at" in d
    assert "cpu" in d and "memory" in d
    assert "process" in d


def test_health_payload_blocks():
    col = DashboardCollector(_settings())
    body = col.health_payload()
    assert body["status"] in ("PASS", "DEGRADED", "FAIL")
    assert "cameras" in body
    assert body["recording"]["state"] == "idle"
    assert body["system"]["storage"]["path"]
    assert body["prebuffer"]["bytes_total"] > 0
    assert "timesync" in body


def test_storage_targets_primary_path():
    primary = Path("./recordings")
    primary.mkdir(parents=True, exist_ok=True)
    usage = disk_usage_at(primary)
    assert usage.accessible
    assert usage.path == primary


def test_recording_status_snapshot():
    storage = StorageManager(Path("./recordings"), Path("./recordings_sub"))
    ctrl = RecordingController(
        storage=storage,
        camera_indices=(0, 1),
        buffer_sec=10.0,
        split_interval_sec=60.0,
        pixel_format="BayerRG8",
        codec="H265",
        bitrate_bps=12_000_000,
        gpu_id=0,
    )
    assert ctrl.status_snapshot()["state"] == "idle"


def test_critical_gpu_temp_fails():
    from cam_acq.monitoring.host_metrics import (
        CpuMetrics,
        GpuMetrics,
        MemoryMetrics,
        SystemMetricsSnapshot,
    )

    col = DashboardCollector(_settings())
    hot = SystemMetricsSnapshot(
        schema_version="1.0",
        collected_at="2026-01-01T00:00:00+09:00",
        cpu=CpuMetrics(percent=10.0, count=8),
        memory=MemoryMetrics(percent=50.0, used_bytes=1, total_bytes=2),
        gpu=GpuMetrics(
            index=0,
            name="test",
            utilization_percent=50.0,
            encoder_percent=10.0,
            decoder_percent=5.0,
            memory_used_mb=100,
            memory_total_mb=16000,
            temperature_c=95,
            power_w=None,
        ),
    )
    health = col.evaluate_health(system=hot)
    assert health.status == "FAIL"


def test_pipeline_hooks_camera_payload():
    from cam_acq.camera.grab import GrabStats

    hooks = PipelineHooks()
    st = GrabStats(camera_index=0, ip="10.0.0.1")
    st.frames_received = 100
    st._fps_window.append(22.5)
    hooks.set_grab_stats(st)
    col = DashboardCollector(_settings(), hooks=hooks)
    cams = col.health_payload()["cameras"]
    assert len(cams) == 1
    assert cams[0]["fps_live"] == 22.5
    assert cams[0]["connection"] == "online"


if __name__ == "__main__":
    test_sample_once_has_schema()
    test_health_payload_blocks()
    test_storage_targets_primary_path()
    test_recording_status_snapshot()
    test_critical_gpu_temp_fails()
    test_pipeline_hooks_camera_payload()
    print("ok")
