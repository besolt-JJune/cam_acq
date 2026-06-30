"""Generate nvinfer config and tiler layout for NUM_CAMERAS = N."""

from __future__ import annotations

import math
import os
from pathlib import Path

from cam_acq.config import Settings, project_root

# Keys patched from Settings when writing generated nvinfer config.
_PATCH_KEYS = frozenset(
    {
        "gpu-id",
        "onnx-file",
        "model-engine-file",
        "labelfile-path",
        "batch-size",
        "custom-lib-path",
    }
)


def tiler_layout(num_cameras: int) -> tuple[int, int]:
    """Return (rows, cols) for nvmultistreamtiler covering N streams (landscape grid)."""
    if num_cameras < 1:
        raise ValueError("num_cameras must be >= 1")
    if num_cameras == 1:
        return 1, 1
    cols = max(1, math.ceil(math.sqrt(num_cameras)))
    rows = math.ceil(num_cameras / cols)
    return rows, cols


def _rel_to_config_dir(path: Path, config_dir: Path) -> str:
    """Path relative to the generated ini directory (nvinfer resolves paths from there)."""
    return os.path.relpath(path.resolve(), config_dir.resolve())


def render_nvinfer_config(
    settings: Settings,
    *,
    root: Path | None = None,
    config_dir: Path | None = None,
) -> str:
    """Build nvinfer ini text with batch-size and paths matching NUM_CAMERAS."""
    base = root or project_root()
    template = base / "configs" / "nvinfer" / "config_infer_primary_yolo.txt"
    if not template.is_file():
        raise FileNotFoundError(f"missing nvinfer template: {template}")

    cfg_dir = config_dir or (base / "configs" / "nvinfer" / ".generated")
    engine = settings.detection_model_path
    if not engine.is_absolute():
        engine = base / engine
    onnx = settings.detection_onnx_path
    if not onnx.is_absolute():
        onnx = base / onnx
    yolo_lib = settings.deepstream_yolo_lib
    if not yolo_lib.is_absolute():
        yolo_lib = base / yolo_lib
    if not yolo_lib.is_file():
        raise FileNotFoundError(
            f"DeepStream-Yolo parser missing: {yolo_lib} (run scripts/setup_deepstream_yolo.sh)"
        )
    labels = base / "models" / "labels.txt"

    values = {
        "gpu-id": str(settings.gpu_id),
        "onnx-file": _rel_to_config_dir(onnx, cfg_dir),
        "model-engine-file": _rel_to_config_dir(engine, cfg_dir),
        "labelfile-path": _rel_to_config_dir(labels, cfg_dir),
        "batch-size": str(settings.num_cameras),
        "custom-lib-path": _rel_to_config_dir(yolo_lib, cfg_dir),
    }

    lines: list[str] = []
    for line in template.read_text().splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else ""
        if key in _PATCH_KEYS:
            lines.append(f"{key}={values[key]}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


def write_nvinfer_config(
    settings: Settings,
    *,
    root: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Write generated nvinfer config; returns path passed to nvinfer config-file-path."""
    base = root or project_root()
    out_dir = output_dir or base / "configs" / "nvinfer" / ".generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"config_infer_primary_b{settings.num_cameras}.txt"
    out_path.write_text(
        render_nvinfer_config(settings, root=base, config_dir=out_dir)
    )
    return out_path
