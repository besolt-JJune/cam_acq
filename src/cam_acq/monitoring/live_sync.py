"""Sync yolo-live grab stats into PipelineHooks (thumbnails come from YOLO input chain)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cam_acq.camera.grab import GrabStats

if TYPE_CHECKING:
    from cam_acq.monitoring.pipeline_hooks import PipelineHooks


def _live_stats_to_grab(st) -> GrabStats:
    """Build GrabStats; recovery is shared so API reads live offline_events."""
    frames, incomplete, open_error, fps_window, connection_offline = st.monitoring_snapshot()
    gs = GrabStats(camera_index=st.camera_index, ip=st.ip)
    gs.frames_received = frames
    gs.incomplete_frames = incomplete
    gs.open_error = open_error
    gs.connection_offline = connection_offline
    gs.recovery = st.recovery
    gs._fps_window = fps_window
    return gs


def sync_live_camera_to_hooks(*, hooks: PipelineHooks, st) -> None:
    """Push one camera's grab stats (call right after GigE reconnect)."""
    hooks.set_grab_stats(_live_stats_to_grab(st))


def sync_live_feed_to_hooks(
    *,
    hooks: PipelineHooks,
    stats_list: list,
) -> None:
    """Push GrabStats with 1s rolling FPS from LiveFeedStats."""
    for st in stats_list:
        hooks.set_grab_stats(_live_stats_to_grab(st))
