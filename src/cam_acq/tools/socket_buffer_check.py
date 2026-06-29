#!/usr/bin/env python3
"""Check Linux socket buffer sizes for GigE (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cam_acq.config import load_settings


def _read_sys_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except OSError:
        return None


def check_socket_buffers(min_bytes: int) -> dict:
    """Read rmem_max/wmem_max and compare to recommended minimum."""
    proc = Path("/proc/sys/net/core")
    rmem = _read_sys_int(proc / "rmem_max")
    wmem = _read_sys_int(proc / "wmem_max")
    ok = (
        rmem is not None
        and wmem is not None
        and rmem >= min_bytes
        and wmem >= min_bytes
    )
    return {
        "schema_version": "1.0",
        "status": "PASS" if ok else "FAIL",
        "min_bytes": min_bytes,
        "min_mib": round(min_bytes / (1024 * 1024), 2),
        "rmem_max": rmem,
        "wmem_max": wmem,
        "rmem_max_mib": round(rmem / (1024 * 1024), 2) if rmem else None,
        "wmem_max_mib": round(wmem / (1024 * 1024), 2) if wmem else None,
        "hint": "sudo sdk/Galaxy_camera/c/SetSocketBufferSize.sh 20971520",
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: 0=PASS, 1=FAIL, 2=config error."""
    parser = argparse.ArgumentParser(description="GigE socket buffer check")
    parser.add_argument("--min-bytes", type=int, default=None, help="Override SOCKET_BUFFER_MIN_BYTES")
    parser.add_argument("--output", type=Path, default=None, help="JSON output path")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except Exception as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    min_b = args.min_bytes if args.min_bytes is not None else settings.socket_buffer_min_bytes
    doc = check_socket_buffers(min_b)
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if doc["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
