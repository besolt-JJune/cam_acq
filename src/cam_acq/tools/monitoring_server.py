#!/usr/bin/env python3
"""Phase 5 monitoring server (host metrics + dashboard; camera hooks deferred)."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from cam_acq.config import load_settings
from cam_acq.logging_setup import setup_logging
from cam_acq.monitoring.api import create_app


def main(argv: list[str] | None = None) -> int:
    """Run local monitoring HTTP server."""
    parser = argparse.ArgumentParser(description="cam_acq monitoring dashboard")
    parser.add_argument("--env", type=str, default=None, help="path to .env")
    parser.add_argument("--port", type=int, default=None, help="override MONITORING_WEB_PORT")
    args = parser.parse_args(argv)

    settings = load_settings(args.env)
    port = args.port if args.port is not None else settings.monitoring_web_port
    setup_logging(settings.log_path)
    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
