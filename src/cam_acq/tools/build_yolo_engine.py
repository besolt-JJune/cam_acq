#!/usr/bin/env python3
"""Export YOLOv8m ONNX and build TensorRT engine for DeepStream (no camera)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from cam_acq.config import load_settings, project_root
from cam_acq.detection.artifacts import (
    VARIANT_COCO,
    VARIANT_PERSON,
    detection_artifact_paths,
)


def _find_trtexec() -> Path | None:
    for candidate in (
        Path("/usr/src/tensorrt/bin/trtexec"),
        Path("/usr/local/tensorrt/bin/trtexec"),
    ):
        if candidate.is_file():
            return candidate
    found = shutil.which("trtexec")
    return Path(found) if found else None


def export_onnx(
    *,
    weights: Path,
    onnx_out: Path,
    input_size: int,
    batch_size: int,
    export_script: Path,
) -> Path:
    """Run DeepStream-Yolo export_yoloV8.py to produce ONNX."""
    onnx_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(export_script),
        "-w",
        str(weights),
        "-s",
        str(input_size),
        str(input_size),
        "--batch",
        str(batch_size),
        "--simplify",
    ]
    subprocess.run(cmd, check=True, cwd=export_script.parent)
    generated = weights.with_suffix(".onnx")
    if not generated.is_file():
        raise FileNotFoundError(f"ONNX not found after export: {generated}")
    if generated.resolve() != onnx_out.resolve():
        shutil.move(str(generated), str(onnx_out))
    return onnx_out


def build_engine(
    *,
    onnx_path: Path,
    engine_path: Path,
    gpu_id: int,
) -> Path:
    """Build FP16 TensorRT engine with trtexec (static-batch ONNX from export_yoloV8.py)."""
    trtexec = _find_trtexec()
    if trtexec is None:
        raise FileNotFoundError(
            "trtexec not found; install TensorRT command-line tools or build engine on target GPU"
        )

    engine_path.parent.mkdir(parents=True, exist_ok=True)
    # export_yoloV8.py: input_names=["input"], static batch (--batch, no --dynamic)
    cmd = [
        str(trtexec),
        f"--onnx={onnx_path}",
        f"--saveEngine={engine_path}",
        "--fp16",
        f"--device={gpu_id}",
    ]
    subprocess.run(cmd, check=True)
    return engine_path


def _require_export_deps() -> None:
    """Fail fast when build-yolo optional deps are not installed."""
    missing: list[str] = []
    for mod in ("onnx", "torch", "ultralytics"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(
            f"Missing packages for YOLO ONNX export: {', '.join(missing)}\n"
            "Run: uv sync --extra build-yolo",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build YOLOv8m ONNX + TensorRT engine")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--weights", type=Path, default=project_root() / "models" / "yolov8m.pt")
    parser.add_argument("--skip-engine", action="store_true", help="ONNX export only")
    parser.add_argument("--batch-size", type=int, default=None, help="defaults to NUM_CAMERAS")
    parser.add_argument(
        "--variant",
        choices=[VARIANT_PERSON, VARIANT_COCO],
        default=VARIANT_PERSON,
        help="person: yolov8m_person.* artifacts (default); coco: yolov8m.*",
    )
    args = parser.parse_args()

    _require_export_deps()
    settings = load_settings(args.env_file)
    batch = args.batch_size if args.batch_size is not None else settings.num_cameras
    root = project_root()
    export_script = root / "third_party" / "DeepStream-Yolo" / "utils" / "export_yoloV8.py"
    if not export_script.is_file():
        print(f"Missing {export_script}; run scripts/setup_deepstream_yolo.sh", file=sys.stderr)
        return 1

    onnx_path, engine_path = detection_artifact_paths(
        variant=args.variant,
        batch_size=batch,
        gpu_id=settings.gpu_id,
        root=root,
    )

    weights = args.weights if args.weights.is_absolute() else root / args.weights
    if not weights.is_file():
        print(f"Downloading yolov8m weights to {weights} ...")
        weights.parent.mkdir(parents=True, exist_ok=True)
        from ultralytics import YOLO

        YOLO("yolov8m.pt").save(str(weights))

    print(
        f"Export ONNX -> {onnx_path} "
        f"(variant={args.variant}, batch={batch}, size={settings.detection_input_size})"
    )
    export_onnx(
        weights=weights,
        onnx_out=onnx_path,
        input_size=settings.detection_input_size,
        batch_size=batch,
        export_script=export_script,
    )

    if args.skip_engine:
        print("ONNX export done (--skip-engine)")
        return 0

    print(f"Build engine -> {engine_path}")
    build_engine(
        onnx_path=onnx_path,
        engine_path=engine_path,
        gpu_id=settings.gpu_id,
    )
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
