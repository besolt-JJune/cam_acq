"""Background uvicorn thread for pipeline-integrated monitoring."""

from __future__ import annotations

import logging
import threading

import uvicorn

from cam_acq.config import Settings
from cam_acq.monitoring.api import create_app
from cam_acq.monitoring.collector import DashboardCollector

logger = logging.getLogger(__name__)


def start_monitoring_server(
    settings: Settings,
    collector: DashboardCollector,
    *,
    host: str = "0.0.0.0",
    port: int | None = None,
) -> threading.Thread:
    """Run FastAPI monitoring in a daemon thread (same process as grab loops)."""
    listen_port = port if port is not None else settings.monitoring_web_port
    app = create_app(settings, collector)

    def _run() -> None:
        logger.info("monitoring listening on %s:%s", host, listen_port)
        uvicorn.run(app, host=host, port=listen_port, log_level="warning")

    thread = threading.Thread(target=_run, name="monitoring-http", daemon=True)
    thread.start()
    return thread
