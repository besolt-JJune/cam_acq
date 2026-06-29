"""Build REST/WebSocket metric blocks from settings and optional pipeline hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cam_acq.camera.grab import GrabStats
from cam_acq.camera.timesync import SessionTimeSync, TimeSyncManager
from cam_acq.config import NOMINAL_FPS, Settings
from cam_acq.recording.buffer import ring_capacity_frames
from cam_acq.recording.storage import StorageManager, disk_usage_at

if TYPE_CHECKING:
    from cam_acq.detection.events import DetectionFrameEvent, RecordingTrigger
    from cam_acq.monitoring.pipeline_hooks import PipelineHooks
    from cam_acq.recording.controller import RecordingController


def _fps_live(stats: GrabStats) -> float | None:
    """Most recent 1s rolling FPS window."""
    live = stats.fps_live
    if live is not None:
        return round(live, 2)
    if stats.fps_avg > 0:
        return round(stats.fps_avg, 2)
    return None


def _connection_state(stats: GrabStats | None) -> str:
    """online | offline | unknown."""
    if stats is None:
        return "unknown"
    if stats.open_error:
        return "offline"
    if stats.frames_received > 0:
        return "online"
    return "unknown"


def camera_payload(
    settings: Settings,
    grab_by_index: dict[int, GrabStats],
    detection_by_index: dict[int, DetectionFrameEvent],
) -> list[dict[str, Any]]:
    """Per-camera stats for dashboard and GET /api/cameras/{id}/stats."""
    out: list[dict[str, Any]] = []
    for ep in settings.cameras:
        gs = grab_by_index.get(ep.index)
        det = detection_by_index.get(ep.index)
        person_count = len(det.detections) if det else 0
        out.append(
            {
                "camera_index": ep.index,
                "ip": ep.ip,
                "interface": ep.interface,
                "connection": _connection_state(gs),
                "open_error": gs.open_error if gs else None,
                "fps_live": _fps_live(gs) if gs else None,
                "fps_avg": round(gs.fps_avg, 2) if gs and gs.fps_avg else None,
                "frames_received": gs.frames_received if gs else 0,
                "frame_drops": gs.frame_drops if gs else 0,
                "incomplete_frames": gs.incomplete_frames if gs else 0,
                "timestamp_regressions": gs.timestamp_regressions if gs else 0,
                "recovery_events": gs.recovery.offline_events if gs else 0,
                "person_count": person_count,
                "last_frame_id": gs.last_frame_id if gs else None,
                "width": gs.width if gs else settings.camera_width,
                "height": gs.height if gs else settings.camera_height,
            }
        )
    return out


def recording_payload(
    controller: RecordingController | None,
    trigger: RecordingTrigger | None,
) -> dict[str, Any]:
    """Recording state from controller and optional auto-trigger."""
    if controller is None:
        active = trigger.is_active if trigger is not None else False
        return {
            "state": "armed" if active else "idle",
            "source": "pipeline" if trigger else None,
            "pending": None,
            "segments_written": 0,
        }
    snap = controller.status_snapshot()
    if trigger is not None and trigger.is_active and snap["state"] == "idle":
        snap = {**snap, "state": "armed", "trigger_active": True}
    return snap


def storage_payload(settings: Settings, storage_mgr: StorageManager | None) -> dict[str, Any]:
    """STORAGE_PATH usage plus active recording path (primary or fallback)."""
    primary = disk_usage_at(settings.storage_path)
    base = primary.to_dict()
    base["management"] = settings.storage_management
    base["warn_percent"] = settings.storage_full_percentage
    if storage_mgr is not None:
        loc = storage_mgr.location
        base["active_path"] = str(loc.path)
        base["active_is_fallback"] = loc.is_fallback
        base["primary_reject_reason"] = storage_mgr.primary_reject_reason
    else:
        base["active_path"] = None
        base["active_is_fallback"] = None
        base["primary_reject_reason"] = None
    return base


def prebuffer_payload(
    settings: Settings,
    controller: RecordingController | None,
) -> dict[str, Any]:
    """Measured ring RAM from controller, or capacity estimate from settings."""
    w = settings.camera_width or 3840
    h = settings.camera_height or 2160
    cap = ring_capacity_frames(NOMINAL_FPS, settings.recording_buffer_sec)
    per_camera_est = cap * w * h
    if controller is not None:
        measured = controller.memory_report()
        total = sum(measured.values())
        return {
            "source": "measured",
            "bytes_total": total,
            "bytes_per_camera": measured,
            "capacity_frames": cap,
            "estimated_bytes_total": per_camera_est * settings.num_cameras,
        }
    return {
        "source": "estimated",
        "bytes_total": per_camera_est * settings.num_cameras,
        "bytes_per_camera": {i: per_camera_est for i in settings.camera_indices},
        "capacity_frames": cap,
        "frame_bytes": w * h,
    }


def timesync_payload(
    session: SessionTimeSync | None,
    grab_by_index: dict[int, GrabStats],
    tolerance_ms: int,
) -> dict[str, Any]:
    """Session anchors and live cross-camera timestamp spread."""
    if session is None:
        return {"available": False}
    offsets_us: list[int] = []
    for anchor in session.anchors:
        gs = grab_by_index.get(anchor.camera_index)
        if (
            gs is None
            or gs.last_timestamp is None
            or anchor.camera_ts0 is None
            or not anchor.tick_frequency_hz
        ):
            continue
        delta = gs.last_timestamp - anchor.camera_ts0
        offsets_us.append(TimeSyncManager.tick_to_us(delta, anchor.tick_frequency_hz))
    live_skew_us: int | None = None
    if len(offsets_us) >= 2:
        live_skew_us = max(offsets_us) - min(offsets_us)
    tol_us = tolerance_ms * 1000
    exceeded = live_skew_us is not None and live_skew_us > tol_us
    return {
        "available": True,
        "strategy": session.strategy,
        "cross_camera_skew_tolerance_ms": tolerance_ms,
        "session_max_skew_us": session.max_cross_camera_skew_us,
        "live_max_skew_us": live_skew_us,
        "skew_exceeded": exceeded,
        "host_session_wall": session.host_t0_wall,
    }


def hooks_snapshot(hooks: PipelineHooks | None) -> tuple[
    dict[int, GrabStats],
    dict[int, Any],
    RecordingController | None,
    RecordingTrigger | None,
    SessionTimeSync | None,
]:
    """Read pipeline hooks or empty defaults."""
    if hooks is None:
        return {}, {}, None, None, None
    grab, det, rec, trig, ts = hooks.snapshot()
    return grab, det, rec, trig, ts
