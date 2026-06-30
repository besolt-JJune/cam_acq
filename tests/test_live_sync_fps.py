"""LiveFeedStats 1s rolling FPS self-check."""

from __future__ import annotations

import time

from cam_acq.tools.deepstream_yolo_live import LiveFeedStats


def test_record_grab_frame_1s_window():
    st = LiveFeedStats(camera_index=0, ip="10.0.0.1")
    st._fps_window_start = time.monotonic() - 1.05
    st._fps_window_frames = 23
    st.record_grab_frame()
    _, _, _, window, _ = st.monitoring_snapshot()
    assert len(window) == 1
    assert 18.0 < window[0] < 28.0


if __name__ == "__main__":
    test_record_grab_frame_1s_window()
    print("ok")
