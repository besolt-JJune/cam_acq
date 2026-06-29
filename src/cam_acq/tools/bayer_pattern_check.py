#!/usr/bin/env python3
"""Grab one Bayer frame and save raw + BMP for each BAYER_FORMAT pattern (visual check)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from cam_acq.camera.bayer import (
    BAYER_FORMATS,
    gst_format_from_bayer_format,
    pattern_from_raw,
    parse_bayer_format,
)
from cam_acq.camera.device import close_camera, open_camera_by_ip
from cam_acq.config import load_settings, setup_galaxy_lib_path
from gxipy.gxidef import GxFrameStatusList, GxSwitchEntry


def grab_one_bayer(*, ip: str) -> tuple[bytes, int, int, int | None]:
    """Open camera, return (payload, width, height, camera_pixel_format_entry)."""
    cam = open_camera_by_ip(ip)
    try:
        cam.TriggerMode.set(GxSwitchEntry.OFF)
        cam.stream_on()
        for _ in range(30):
            raw = cam.data_stream[0].get_image(timeout=2000)
            if raw is None:
                continue
            if raw.get_status() != GxFrameStatusList.SUCCESS:
                continue
            payload = raw.get_data()
            if payload is None:
                continue
            pf = None
            try:
                pf = int(raw.get_pixel_format())
            except (TypeError, ValueError):
                pass
            return bytes(payload), int(raw.get_width()), int(raw.get_height()), pf
        raise RuntimeError("no complete frame within 30 attempts")
    finally:
        try:
            cam.stream_off()
        except Exception:
            pass
        close_camera(cam)


def run_bayer_pattern_check(
    *,
    camera_index: int,
    output_dir: Path,
    env_file: Path | None,
) -> int:
    """Save cam{N}.raw and cam{N}_{RGGB|GRBG|GBRG|BGGR}.bmp for pattern comparison."""
    settings = load_settings(env_file)
    setup_galaxy_lib_path()

    cam = next((c for c in settings.cameras if c.index == camera_index), None)
    if cam is None:
        print(f"camera index {camera_index} not in config", file=sys.stderr)
        return 1

    data, width, height, pf_entry = grab_one_bayer(ip=cam.ip)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / f"cam{camera_index}.raw"
    raw_path.write_bytes(data)

    class _Raw:
        def get_pixel_format(self):
            return pf_entry

    camera_pattern = pattern_from_raw(_Raw()) if pf_entry is not None else None
    env_pattern = parse_bayer_format(settings.bayer_format)

    # gi after gxipy grab (import order; see record_test / yolo-live)
    from cam_acq.camera.debayer_gst import bayer8_to_rgb

    bmp_paths: dict[str, str] = {}
    for pattern in BAYER_FORMATS:
        gst_fmt = gst_format_from_bayer_format(pattern)
        rgb = bayer8_to_rgb(data, width=width, height=height, gst_bayer_format=gst_fmt)
        out = output_dir / f"cam{camera_index}_{pattern}.bmp"
        Image.fromarray(rgb, mode="RGB").save(out)
        bmp_paths[pattern] = str(out)

    report = {
        "schema_version": "1.0",
        "status": "PASS",
        "camera_index": camera_index,
        "ip": cam.ip,
        "width": width,
        "height": height,
        "raw_bytes": len(data),
        "raw_path": str(raw_path),
        "pixel_format_env": settings.pixel_format,
        "bayer_format_env": env_pattern,
        "camera_reported_pattern": camera_pattern,
        "camera_pixel_format_entry": pf_entry,
        "bmp_paths": bmp_paths,
        "hint": "Compare BMPs visually; set BAYER_FORMAT to the pattern with natural colors.",
    }
    report_path = output_dir / f"cam{camera_index}_pattern_check.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Save one Bayer raw frame and BMP per BAYER_FORMAT for pattern check"
    )
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=Path("healthcheck/bayer_pattern"))
    args = parser.parse_args()
    return run_bayer_pattern_check(
        camera_index=args.camera_index,
        output_dir=args.output_dir,
        env_file=args.env_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
