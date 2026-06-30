"""nvinfer config generation and tiler layout (no GPU)."""

import os
from contextlib import contextmanager
from pathlib import Path

from cam_acq.config import load_settings, project_root
from cam_acq.detection.artifacts import engine_batch_size, validate_detection_engine
from cam_acq.detection.nvinfer_config import render_nvinfer_config, tiler_layout, write_nvinfer_config


@contextmanager
def _env(overrides: dict[str, str]):
    """Temporarily set env vars for load_settings()."""
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for k, prev in saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def test_tiler_layout():
    assert tiler_layout(1) == (1, 1)
    assert tiler_layout(2) == (1, 2)
    assert tiler_layout(3) == (2, 2)
    assert tiler_layout(4) == (2, 2)
    assert tiler_layout(6) == (2, 3)


def test_render_nvinfer_config_paths_relative_to_generated_dir():
    root = project_root()
    cfg_dir = root / "configs" / "nvinfer" / ".generated"
    with _env(
        {
            "NUM_CAMERAS": "3",
            "CAMERA0_IP": "10.0.0.1",
            "CAMERA1_IP": "10.0.0.2",
            "CAMERA2_IP": "10.0.0.3",
            "DETECTION_MODEL_PATH": "models/yolov8m_person_b3_gpu0_fp16.engine",
        }
    ):
        s = load_settings()
        text = render_nvinfer_config(s, root=root, config_dir=cfg_dir)
    assert "batch-size=3\n" in text
    assert "custom-lib-path=../../../third_party/" in text
    assert "labelfile-path=../../../models/labels.txt" in text
    lib_line = [ln for ln in text.splitlines() if ln.startswith("custom-lib-path=")][0]
    lib_path = (cfg_dir / lib_line.split("=", 1)[1]).resolve()
    assert lib_path.name == "libnvdsinfer_custom_impl_Yolo.so"


def test_render_nvinfer_config_batch_from_num_cameras():
    with _env(
        {
            "NUM_CAMERAS": "3",
            "CAMERA0_IP": "10.0.0.1",
            "CAMERA1_IP": "10.0.0.2",
            "CAMERA2_IP": "10.0.0.3",
            "DETECTION_MODEL_PATH": "models/yolov8m_person_b3_gpu0_fp16.engine",
        }
    ):
        s = load_settings()
        text = render_nvinfer_config(
            s, root=project_root(), config_dir=project_root() / "configs" / "nvinfer" / ".generated"
        )
    assert "batch-size=3\n" in text
    assert "yolov8m_person_b3_gpu0_fp16.engine" in text


def test_validate_detection_engine_batch_mismatch(tmp_path=None):
    base = tmp_path or Path("/tmp/cam_acq_test_engine")
    engine = base / "models" / "yolov8m_person_b2_gpu0_fp16.engine"
    engine.parent.mkdir(parents=True, exist_ok=True)
    engine.touch()
    with _env(
        {
            "NUM_CAMERAS": "3",
            "CAMERA0_IP": "10.0.0.1",
            "CAMERA1_IP": "10.0.0.2",
            "CAMERA2_IP": "10.0.0.3",
            "DETECTION_MODEL_PATH": str(engine),
        }
    ):
        s = load_settings()
        try:
            validate_detection_engine(s, root=base)
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "batch 2 != NUM_CAMERAS=3" in str(exc)


def test_engine_batch_size_parses_filename():
    assert engine_batch_size(Path("yolov8m_person_b3_gpu0_fp16.engine")) == 3
    assert engine_batch_size(Path("no_batch.engine")) is None


def test_write_nvinfer_config(tmp_path=None):
    root = project_root()
    template = root / "configs" / "nvinfer" / "config_infer_primary_yolo.txt"
    if not template.is_file():
        return
    out_base = tmp_path or Path("/tmp/cam_acq_nvinfer_gen")
    with _env(
        {
            "NUM_CAMERAS": "2",
            "CAMERA0_IP": "10.0.0.1",
            "CAMERA1_IP": "10.0.0.2",
            "DETECTION_MODEL_PATH": "models/yolov8m_person_b2_gpu0_fp16.engine",
        }
    ):
        s = load_settings()
        out = write_nvinfer_config(s, root=root, output_dir=out_base / "gen")
    assert out.is_file()
    assert out.name == "config_infer_primary_b2.txt"


if __name__ == "__main__":
    test_tiler_layout()
    test_render_nvinfer_config_paths_relative_to_generated_dir()
    test_render_nvinfer_config_batch_from_num_cameras()
    test_validate_detection_engine_batch_mismatch()
    test_engine_batch_size_parses_filename()
    test_write_nvinfer_config()
    print("ok")
