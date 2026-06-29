"""Session JSON and per-frame JSONL writers (05_metadata_schema.md)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from cam_acq.config import NOMINAL_FPS
from cam_acq.detection.events import TriggerDecision


def write_session_json(
    path: Path,
    *,
    camera_index: int,
    segment_index: int,
    video_file: str,
    frames_file: str,
    codec: str,
    width: int,
    height: int,
    trigger: TriggerDecision,
    buffer_sec: float,
    split_interval_sec: float,
    segment_start_host_us: int,
    segment_end_host_us: int,
    storage_path: str,
    storage_fallback: bool,
    time_sync: dict[str, Any],
) -> None:
    """Write segment session metadata JSON."""
    doc = {
        "schema_version": "1.0",
        "recording_id": str(uuid.uuid4()),
        "segment_index": segment_index,
        "camera_index": camera_index,
        "video_file": video_file,
        "codec": codec,
        "resolution": {"width": width, "height": height},
        "fps_nominal": NOMINAL_FPS,
        "trigger": trigger.as_dict(),
        "buffer": {"pre_sec": buffer_sec, "post_sec": buffer_sec},
        "time_sync": time_sync,
        "split": {
            "interval_sec": split_interval_sec,
            "segment_start_host_us": segment_start_host_us,
            "segment_end_host_us": segment_end_host_us,
        },
        "storage": {
            "active_path": storage_path,
            "is_fallback": storage_fallback,
        },
        "frames_file": frames_file,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def write_frames_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write NDJSON frame metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
