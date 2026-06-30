"""YOLO ONNX/engine path helpers (batch = NUM_CAMERAS)."""

from __future__ import annotations

import re
from pathlib import Path

from cam_acq.config import Settings, project_root

VARIANT_COCO = "coco"
VARIANT_PERSON = "person"

_BATCH_IN_NAME = re.compile(r"_b(\d+)_")


def detection_artifact_paths(
    *,
    variant: str,
    batch_size: int,
    gpu_id: int,
    root: Path | None = None,
) -> tuple[Path, Path]:
    """Return (onnx_path, engine_path) for coco vs person-only deployment naming."""
    base = root or project_root()
    models = base / "models"
    if variant == VARIANT_PERSON:
        onnx = models / "yolov8m_person.onnx"
        engine = models / f"yolov8m_person_b{batch_size}_gpu{gpu_id}_fp16.engine"
    elif variant == VARIANT_COCO:
        onnx = models / "yolov8m.onnx"
        engine = models / f"yolov8m_b{batch_size}_gpu{gpu_id}_fp16.engine"
    else:
        raise ValueError(f"unknown variant: {variant!r} (use {VARIANT_PERSON!r} or {VARIANT_COCO!r})")
    return onnx, engine


def resolve_detection_engine(settings: Settings, root: Path | None = None) -> Path:
    """Resolve DETECTION_MODEL_PATH relative to repo root."""
    base = root or project_root()
    engine = settings.detection_model_path
    return engine if engine.is_absolute() else base / engine


def engine_batch_size(engine_path: Path) -> int | None:
    """Parse batch N from ``*_b{N}_gpu*`` engine filename, or None."""
    match = _BATCH_IN_NAME.search(engine_path.name)
    return int(match.group(1)) if match else None


def validate_detection_engine(settings: Settings, root: Path | None = None) -> Path:
    """Ensure engine exists and its batch suffix matches NUM_CAMERAS."""
    engine = resolve_detection_engine(settings, root)
    if not engine.is_file():
        raise FileNotFoundError(
            f"TensorRT engine not found: {engine} "
            f"(run: cam-acq-build-yolo --batch-size {settings.num_cameras})"
        )
    batch = engine_batch_size(engine)
    if batch is None:
        raise ValueError(
            f"DETECTION_MODEL_PATH filename must contain _b{{N}}_ (got {engine.name})"
        )
    if batch != settings.num_cameras:
        raise ValueError(
            f"engine batch {batch} != NUM_CAMERAS={settings.num_cameras} "
            f"({engine.name}); rebuild with cam-acq-build-yolo --batch-size {settings.num_cameras}"
        )
    return engine
