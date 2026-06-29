#!/usr/bin/env python3
"""HTTP client for runtime camera params (run while grab + --with-monitoring)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from cam_acq.camera.params import ALL_PARAM_FIELDS
from cam_acq.config import load_settings

# CLI flag names → PATCH JSON keys
_FLAG_TO_FIELD: dict[str, str] = {
    "exposure_time_us": "exposure_time_us",
    "exposure_auto": "exposure_auto",
    "acquisition_frame_rate": "acquisition_frame_rate",
    "gain": "gain",
    "gain_auto": "gain_auto",
    "gamma_mode": "gamma_mode",
    "gamma": "gamma",
}


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _request(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any]]:
    """Return (status_code, json body or error envelope)."""
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {"detail": exc.reason}
        except json.JSONDecodeError:
            payload = {"detail": raw or exc.reason}
        return exc.code, payload


def get_params(*, host: str, port: int, camera_index: int) -> tuple[int, dict[str, Any]]:
    """GET /api/cameras/{id}/params."""
    url = f"{_base_url(host, port)}/api/cameras/{camera_index}/params"
    return _request("GET", url)


def patch_params(
    *,
    host: str,
    port: int,
    camera_index: int,
    updates: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """PATCH /api/cameras/{id}/params."""
    url = f"{_base_url(host, port)}/api/cameras/{camera_index}/params"
    return _request("PATCH", url, body=updates)


def wait_applied(
    *,
    host: str,
    port: int,
    camera_index: int,
    timeout_sec: float,
    poll_sec: float,
) -> tuple[bool, dict[str, Any]]:
    """Poll GET until apply_pending is false or timeout."""
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, body = get_params(host=host, port=port, camera_index=camera_index)
        last = body
        if status != 200:
            return False, body
        if not body.get("apply_pending"):
            return body.get("last_apply_error") is None, body
        time.sleep(poll_sec)
    return False, last


def _patch_body_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Build PATCH body from CLI flags or --json file."""
    if args.json is not None:
        data = json.loads(args.json.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("--json must be a JSON object")
        return {k: v for k, v in data.items() if k in ALL_PARAM_FIELDS and v is not None}

    body: dict[str, Any] = {}
    for flag, field in _FLAG_TO_FIELD.items():
        val = getattr(args, flag, None)
        if val is not None:
            body[field] = val
    return body


def main(argv: list[str] | None = None) -> int:
    """GET or PATCH camera params on a running grab+monitoring process."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env", type=str, default=None, help="path to .env (default port)")
    common.add_argument("--host", default="127.0.0.1", help="monitoring API host")
    common.add_argument("--port", type=int, default=None, help="override MONITORING_WEB_PORT")
    common.add_argument("--camera", type=int, required=True, help="camera_index (0-based)")

    parser = argparse.ArgumentParser(
        description=(
            "Runtime camera parameter client (HTTP). "
            "Requires grab process with --with-monitoring on the same host."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("get", parents=[common], help="read current / last-applied parameters")

    patch_p = sub.add_parser(
        "patch",
        parents=[common],
        help="apply parameters (user request → grab thread)",
    )
    patch_p.add_argument("--json", type=argparse.FileType("r"), help="PATCH body JSON file")
    patch_p.add_argument(
        "--exposure-time-us",
        "--exposure_time_us",
        type=float,
        dest="exposure_time_us",
        metavar="MICROSEC",
    )
    patch_p.add_argument(
        "--exposure-auto",
        "--exposure_auto",
        dest="exposure_auto",
        metavar="MODE",
        help="Off | Continuous | Once (see GET response for device labels)",
    )
    patch_p.add_argument(
        "--acquisition-frame-rate",
        "--acquisition_frame_rate",
        type=float,
        dest="acquisition_frame_rate",
        metavar="FPS",
    )
    patch_p.add_argument("--gain", type=float, metavar="DB")
    patch_p.add_argument(
        "--gain-auto",
        "--gain_auto",
        dest="gain_auto",
        metavar="MODE",
        help="Off | Continuous | Once",
    )
    patch_p.add_argument(
        "--gamma-mode",
        "--gamma_mode",
        dest="gamma_mode",
        metavar="MODE",
        help="e.g. sRGB | User (see GET response)",
    )
    patch_p.add_argument("--gamma", type=float)
    patch_p.add_argument(
        "--wait",
        action="store_true",
        help="poll until apply_pending clears (grab thread applied or failed)",
    )
    patch_p.add_argument("--wait-timeout", type=float, default=5.0)
    patch_p.add_argument("--wait-poll", type=float, default=0.2)

    args = parser.parse_args(argv)
    settings = load_settings(args.env)
    port = args.port if args.port is not None else settings.monitoring_web_port
    host = args.host

    if args.command == "get":
        status, body = get_params(host=host, port=port, camera_index=args.camera)
        print(json.dumps(body, indent=2))
        return 0 if status == 200 else 1

    updates = _patch_body_from_args(args)
    if not updates:
        print("patch: no parameter fields (use flags or --json)", file=sys.stderr)
        return 1

    status, body = patch_params(
        host=host,
        port=port,
        camera_index=args.camera,
        updates=updates,
    )
    print(json.dumps(body, indent=2))
    if status not in (200, 201):
        return 1

    if args.wait:
        ok, final = wait_applied(
            host=host,
            port=port,
            camera_index=args.camera,
            timeout_sec=args.wait_timeout,
            poll_sec=args.wait_poll,
        )
        print(json.dumps({"wait_applied": ok, **final}, indent=2))
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
