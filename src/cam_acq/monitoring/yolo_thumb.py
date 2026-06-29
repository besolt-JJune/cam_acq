"""Drain YOLO-input RGB (from GStreamer probe or push_batch) into ThumbnailStore."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cam_acq.monitoring.pipeline_hooks import PipelineHooks


def sync_yolo_thumbnails(
    *,
    hooks: PipelineHooks | None,
    stats_list: list,
    thumb_last: dict[int, float],
    interval_sec: float,
) -> None:
    """JPEG-encode latest YOLO resize RGB on the main thread (probe only queues RGB)."""
    if hooks is None:
        return
    now = time.monotonic()
    for st in stats_list:
        rgb = st.peek_yolo_rgb()
        if rgb is None:
            continue
        cam = st.camera_index
        if now - thumb_last.get(cam, 0.0) < interval_sec:
            continue
        thumb_last[cam] = now
        hooks.thumbnails.update_rgb(cam, rgb)
