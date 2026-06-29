"""Config loader self-check (no camera required)."""

from pathlib import Path

from cam_acq.config import load_settings, project_root


def test_load_settings_from_example():
    example = project_root() / ".env.example"
    if not example.is_file():
        return
    s = load_settings(example)
    assert s.num_cameras >= 1
    assert len(s.cameras) == s.num_cameras
    assert s.camera_indices == tuple(range(s.num_cameras))
    assert all(c.ip for c in s.cameras)
    assert s.resize_width > 0
    assert s.detection_input_size > 0
    assert s.monitoring_web_port > 0
    assert s.system_metrics_poll_sec > 0


def test_min_frames_expected():
    from cam_acq.camera.grab import min_frames_expected

    assert min_frames_expected(60.0) == int(60 * 23 * 0.95)


if __name__ == "__main__":
    test_load_settings_from_example()
    test_min_frames_expected()
    print("ok")
