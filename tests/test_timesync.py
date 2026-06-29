"""TimeSyncManager pure-logic self-check (no camera)."""

from cam_acq.camera.timesync import CameraTimeAnchor, SessionTimeSync, TimeSyncManager


def test_tick_to_us_1ghz():
    assert TimeSyncManager.tick_to_us(1_000_000_000, 1_000_000_000) == 1_000_000
    assert TimeSyncManager.tick_to_us(371_100, 1_000_000_000) == 371


def test_max_cross_camera_skew():
    anchors = (
        CameraTimeAnchor(0, "10.0.0.1", 371_100, 1_000_000_000, True),
        CameraTimeAnchor(1, "10.0.0.2", 336_600, 1_000_000_000, True),
    )
    skew = TimeSyncManager._max_cross_camera_skew_us(anchors)
    assert skew == 35


def test_session_to_dict_keys():
    session = SessionTimeSync(
        strategy="host_clock_sync",
        host_t0_monotonic=100.0,
        host_t0_wall="2026-01-01T00:00:00+00:00",
        timestamp_reset_on_session=True,
        cross_camera_skew_tolerance_ms=50,
        anchors=(),
    )
    d = session.to_dict()
    assert d["strategy"] == "host_clock_sync"
    assert "cameras" in d


if __name__ == "__main__":
    test_tick_to_us_1ghz()
    test_max_cross_camera_skew()
    test_session_to_dict_keys()
    print("ok")
