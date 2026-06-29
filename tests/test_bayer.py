"""Bayer format mapping self-check."""

from cam_acq.camera.bayer import (
    BAYER_FORMAT_RGGB,
    gst_bayer_format,
    gst_format_from_bayer_format,
    parse_bayer_format,
    pattern_from_raw,
)


def test_parse_bayer_format():
    assert parse_bayer_format("rggb") == BAYER_FORMAT_RGGB
    assert parse_bayer_format("GRBG") == "GRBG"


def test_gst_format_from_bayer_format():
    assert gst_format_from_bayer_format("RGGB") == "rggb"
    assert gst_format_from_bayer_format("BGGR") == "bggr"


def test_gst_bayer_format_legacy_pixel_label():
    assert gst_bayer_format("BayerRG8") == "rggb"
    assert gst_bayer_format("BayerGR8") == "grbg"


def test_pattern_from_raw():
    from gxipy.gxidef import GxPixelFormatEntry

    class _Raw:
        def get_pixel_format(self):
            return GxPixelFormatEntry.BAYER_RG8

    assert pattern_from_raw(_Raw()) == BAYER_FORMAT_RGGB


if __name__ == "__main__":
    test_parse_bayer_format()
    test_gst_format_from_bayer_format()
    test_gst_bayer_format_legacy_pixel_label()
    test_pattern_from_raw()
    print("ok")
