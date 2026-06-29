"""Sync yolo-live grab stats into PipelineHooks (thumbnails come from YOLO input chain)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cam_acq.camera.grab import GrabStats

if TYPE_CHECKING:
    from cam_acq.monitoring.pipeline_hooks import PipelineHooks


def sync_live_feed_to_hooks(
    *,
    hooks: PipelineHooks,
    stats_list: list,
) -> None:
    """Push GrabStats with 1s rolling FPS from LiveFeedStats."""
    for st in stats_list:
        frames, incomplete, open_error, fps_window = st.monitoring_snapshot()
        gs = GrabStats(camera_index=st.camera_index, ip=st.ip)
        gs.frames_received = frames
        gs.incomplete_frames = incomplete
        gs.open_error = open_error
        gs._fps_window = fps_window
        hooks.set_grab_stats(gs)
