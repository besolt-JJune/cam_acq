"""Aggregate dashboard snapshots from host metrics, storage, and pipeline hooks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from cam_acq.config import Settings
from cam_acq.monitoring.host_metrics import HostMetricsSampler, SystemMetricsSnapshot
from cam_acq.monitoring.payloads import (
    camera_payload,
    hooks_snapshot,
    prebuffer_payload,
    recording_payload,
    storage_payload,
    timesync_payload,
)
from cam_acq.monitoring.pipeline_hooks import PipelineHooks
from cam_acq.recording.storage import PathDiskUsage, StorageManager, disk_usage_at

logger = logging.getLogger(__name__)

HealthStatus = Literal["PASS", "DEGRADED", "FAIL"]
SCHEMA_VERSION = "1.0"
MIN_CAMERA_FPS = 22.0


@dataclass(frozen=True)
class HealthSummary:
    """Overall health from host, storage, camera, and timesync thresholds."""

    status: HealthStatus
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "warnings": list(self.warnings)}


class DashboardCollector:
    """In-process metrics aggregator for REST/WebSocket dashboard."""

    def __init__(
        self,
        settings: Settings,
        sampler: HostMetricsSampler | None = None,
        *,
        hooks: PipelineHooks | None = None,
        storage_manager: StorageManager | None = None,
    ) -> None:
        self._settings = settings
        ifaces = tuple(
            c.interface for c in settings.cameras if c.interface
        )
        self._sampler = sampler or HostMetricsSampler(
            gpu_index=settings.gpu_id,
            poll_sec=settings.system_metrics_poll_sec,
            network_interfaces=ifaces,
        )
        self._hooks = hooks or PipelineHooks()
        self._storage_mgr = storage_manager
        if self._storage_mgr is None:
            try:
                self._storage_mgr = StorageManager(
                    settings.storage_path,
                    settings.storage_path_sub,
                    management=settings.storage_management,
                    full_percentage=settings.storage_full_percentage,
                )
            except OSError as exc:
                logger.warning("StorageManager init failed: %s", exc)

    @property
    def hooks(self) -> PipelineHooks:
        """Pipeline bindings for grab/detection/recording loops."""
        return self._hooks

    def start(self) -> None:
        """Start background host metrics sampling."""
        self._sampler.start()

    def stop(self) -> None:
        """Stop background host metrics sampling."""
        self._sampler.stop()

    def system_metrics(self) -> SystemMetricsSnapshot:
        """Latest host metrics snapshot."""
        return self._sampler.snapshot()

    def storage_metrics(self) -> PathDiskUsage:
        """Disk usage for configured STORAGE_PATH."""
        return disk_usage_at(self._settings.storage_path)

    def system_payload(self) -> dict[str, Any]:
        """Host metrics plus storage (STORAGE_PATH + active recording path)."""
        body = self.system_metrics().to_dict()
        body["storage"] = storage_payload(self._settings, self._storage_mgr)
        return body

    def _build_payload(self) -> dict[str, Any]:
        system = self.system_payload()
        grab, det, rec, trig, tsync = hooks_snapshot(self._hooks)
        cameras = camera_payload(self._settings, grab, det)
        recording = recording_payload(rec, trig)
        prebuffer = prebuffer_payload(self._settings, rec)
        timesync = timesync_payload(
            tsync, grab, self._settings.cross_camera_skew_tolerance_ms
        )
        health = self.evaluate_health(
            system=self.system_metrics(),
            storage=self.storage_metrics(),
            cameras=cameras,
            timesync=timesync,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "collected_at": system["collected_at"],
            "health": health.to_dict(),
            "features": self.features_payload(),
            "stream": {
                "width": self._settings.resize_width,
                "height": self._settings.resize_height,
                "max_fps": self._settings.ui_max_display_fps,
            },
            "system": system,
            "cameras": cameras,
            "recording": recording,
            "prebuffer": prebuffer,
            "timesync": timesync,
        }

    def evaluate_health(
        self,
        *,
        system: SystemMetricsSnapshot | None = None,
        storage: PathDiskUsage | None = None,
        cameras: list[dict[str, Any]] | None = None,
        timesync: dict[str, Any] | None = None,
    ) -> HealthSummary:
        """Map metrics to PASS/DEGRADED/FAIL using .env warn thresholds."""
        snap = system or self.system_metrics()
        store = storage if storage is not None else self.storage_metrics()
        s = self._settings
        warnings: list[str] = []

        if snap.cpu.percent is not None and snap.cpu.percent >= s.cpu_warn_percent:
            warnings.append(f"cpu_high:{snap.cpu.percent:.1f}")
        if snap.memory.percent is not None and snap.memory.percent >= s.ram_warn_percent:
            warnings.append(f"ram_high:{snap.memory.percent:.1f}")
        if not store.accessible:
            warnings.append("storage_inaccessible")
        elif store.percent is not None and store.percent >= s.storage_full_percentage:
            warnings.append(f"storage_high:{store.percent:.1f}")

        status: HealthStatus = "PASS"
        if snap.gpu is not None:
            gpu = snap.gpu
            if gpu.temperature_c is not None and gpu.temperature_c >= s.gpu_temp_critical_c:
                warnings.append(f"gpu_temp_critical:{gpu.temperature_c}")
                status = "FAIL"
            elif gpu.temperature_c is not None and gpu.temperature_c >= s.gpu_temp_warn_c:
                warnings.append(f"gpu_temp_warn:{gpu.temperature_c}")
            if (
                gpu.utilization_percent is not None
                and gpu.utilization_percent >= s.gpu_util_warn_percent
            ):
                warnings.append(f"gpu_util_high:{gpu.utilization_percent:.0f}")

        if cameras is None:
            grab, det, rec, trig, ts = hooks_snapshot(self._hooks)
            cameras = camera_payload(s, grab, det)
        for cam in cameras:
            idx = cam["camera_index"]
            if cam.get("connection") == "offline":
                warnings.append(f"camera_offline:{idx}")
            fps = cam.get("fps_live")
            if fps is not None and fps < MIN_CAMERA_FPS:
                warnings.append(f"camera_fps_low:{idx}:{fps}")
            if cam.get("frame_drops", 0) > 0:
                warnings.append(f"camera_drops:{idx}:{cam['frame_drops']}")
            if cam.get("incomplete_frames", 0) > 0:
                warnings.append(f"camera_incomplete:{idx}:{cam['incomplete_frames']}")

        if timesync is None:
            grab, _, _, _, ts = hooks_snapshot(self._hooks)
            timesync = timesync_payload(ts, grab, s.cross_camera_skew_tolerance_ms)
        if timesync.get("skew_exceeded"):
            warnings.append(f"timesync_skew:{timesync.get('live_max_skew_us')}")

        if status != "FAIL" and warnings:
            status = "DEGRADED"
        return HealthSummary(status=status, warnings=tuple(warnings))

    def health_payload(self) -> dict[str, Any]:
        """GET /api/health body."""
        body = self._build_payload()
        health = body["health"]
        return {
            "schema_version": body["schema_version"],
            "collected_at": body["collected_at"],
            "status": health["status"],
            "warnings": health["warnings"],
            "features": body["features"],
            "system": body["system"],
            "cameras": body["cameras"],
            "recording": body["recording"],
            "prebuffer": body["prebuffer"],
            "timesync": body["timesync"],
        }

    def dashboard_payload(self) -> dict[str, Any]:
        """WebSocket push body."""
        return self._build_payload()

    def camera_stats(self, camera_index: int) -> dict[str, Any] | None:
        """Stats for one camera_index; None if not configured."""
        for cam in self.health_payload()["cameras"]:
            if cam["camera_index"] == camera_index:
                return cam
        return None

    def manual_recording_start(self) -> dict[str, Any]:
        """Start manual all-channel recording until manual_recording_stop."""
        _, _, rec, trig, _ = hooks_snapshot(self._hooks)
        if rec is None or trig is None:
            raise RuntimeError("recording not enabled")
        action = trig.manual_start()
        rec.apply_trigger_action(action)
        assert action.decision is not None
        return action.decision.as_dict()

    def manual_recording_stop(self) -> dict[str, Any]:
        """End manual recording; encode after pending window is ready."""
        _, _, rec, trig, _ = hooks_snapshot(self._hooks)
        if rec is None or trig is None:
            raise RuntimeError("recording not enabled")
        action = trig.manual_stop()
        rec.apply_trigger_action(action)
        pending = rec.status_snapshot(manual_active=False).get("pending") or {}
        return {"ok": True, "ended_at_host_us": action.ended_at_host_us, "pending": pending}

    def manual_recording_trigger(self) -> dict[str, Any]:
        """Alias for manual_recording_start (legacy API name)."""
        return self.manual_recording_start()

    def features_payload(self) -> dict[str, bool]:
        """Which optional dashboard features are active."""
        _, _, rec, trig, _ = hooks_snapshot(self._hooks)
        return {
            "params": self._hooks.param_store is not None,
            "recording": rec is not None and trig is not None,
            "stream": self._hooks.param_store is not None,
        }
