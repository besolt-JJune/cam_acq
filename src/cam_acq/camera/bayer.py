"""Bayer pattern (BAYER_FORMAT) and GStreamer bayer2rgb format strings."""

from __future__ import annotations

from typing import Any

# User-facing .env values (uppercase)
BAYER_FORMAT_RGGB = "RGGB"
BAYER_FORMAT_GRBG = "GRBG"
BAYER_FORMAT_GBRG = "GBRG"
BAYER_FORMAT_BGGR = "BGGR"

BAYER_FORMATS: tuple[str, ...] = (
    BAYER_FORMAT_RGGB,
    BAYER_FORMAT_GRBG,
    BAYER_FORMAT_GBRG,
    BAYER_FORMAT_BGGR,
)

_PATTERN_TO_GST: dict[str, str] = {
    BAYER_FORMAT_RGGB: "rggb",
    BAYER_FORMAT_GRBG: "grbg",
    BAYER_FORMAT_GBRG: "gbrg",
    BAYER_FORMAT_BGGR: "bggr",
}

# Legacy Galaxy PIXEL_FORMAT label → BAYER_FORMAT
_PIXEL_LABEL_TO_PATTERN: dict[str, str] = {
    "BayerRG8": BAYER_FORMAT_RGGB,
    "BayerGR8": BAYER_FORMAT_GRBG,
    "BayerGB8": BAYER_FORMAT_GBRG,
    "BayerBG8": BAYER_FORMAT_BGGR,
}

_ENTRY_TO_PATTERN: dict[int, str] = {}


def _ensure_entry_map() -> dict[int, str]:
    if _ENTRY_TO_PATTERN:
        return _ENTRY_TO_PATTERN
    from gxipy.gxidef import GxPixelFormatEntry

    _ENTRY_TO_PATTERN.update(
        {
            GxPixelFormatEntry.BAYER_RG8: BAYER_FORMAT_RGGB,
            GxPixelFormatEntry.BAYER_GR8: BAYER_FORMAT_GRBG,
            GxPixelFormatEntry.BAYER_GB8: BAYER_FORMAT_GBRG,
            GxPixelFormatEntry.BAYER_BG8: BAYER_FORMAT_BGGR,
        }
    )
    return _ENTRY_TO_PATTERN


def parse_bayer_format(value: str) -> str:
    """Parse BAYER_FORMAT env; return uppercase RGGB|GRBG|GBRG|BGGR."""
    key = value.strip().upper()
    if key not in _PATTERN_TO_GST:
        allowed = ", ".join(BAYER_FORMATS)
        raise ValueError(f"invalid BAYER_FORMAT {value!r}; expected one of: {allowed}")
    return key


def gst_format_from_bayer_format(bayer_format: str) -> str:
    """Map BAYER_FORMAT to GStreamer video/x-bayer format= (lowercase)."""
    return _PATTERN_TO_GST[parse_bayer_format(bayer_format)]


def pattern_from_pixel_label(pixel_format: str) -> str | None:
    """Map PIXEL_FORMAT env (BayerRG8, …) to BAYER_FORMAT pattern."""
    return _PIXEL_LABEL_TO_PATTERN.get(pixel_format)


def pattern_from_raw(raw_image: Any) -> str | None:
    """Map gxipy RawImage pixel format to BAYER_FORMAT pattern."""
    try:
        entry = int(raw_image.get_pixel_format())
    except (AttributeError, TypeError, ValueError):
        return None
    return _ensure_entry_map().get(entry)


def gst_bayer_format(pixel_format: str) -> str:
    """Legacy: PIXEL_FORMAT label → GStreamer format (prefer BAYER_FORMAT in new code)."""
    pattern = pattern_from_pixel_label(pixel_format)
    if pattern is not None:
        return gst_format_from_bayer_format(pattern)
    return "rggb"


def resolve_gst_bayer_format(*, bayer_format: str) -> str:
    """GStreamer debayer format from configured BAYER_FORMAT."""
    return gst_format_from_bayer_format(bayer_format)
