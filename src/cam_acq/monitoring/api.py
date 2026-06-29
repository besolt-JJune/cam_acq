"""FastAPI monitoring server: REST, WebSocket, static dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from cam_acq.config import Settings
from cam_acq.monitoring.collector import DashboardCollector

logger = logging.getLogger(__name__)
_STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings, collector: DashboardCollector | None = None) -> FastAPI:
    """Build FastAPI app wired to a DashboardCollector instance."""
    col = collector or DashboardCollector(settings)
    app = FastAPI(title="Data Acquisition", version="0.1.0")

    @app.on_event("startup")
    async def _startup() -> None:
        col.start()
        logger.info("monitoring collector started (poll=%ss)", settings.system_metrics_poll_sec)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        col.stop()

    @app.get("/")
    async def index() -> FileResponse:
        """Serve dashboard HTML (system panel; camera grid deferred)."""
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> JSONResponse:
        """System health summary plus stub camera/recording blocks."""
        return JSONResponse(col.health_payload())

    @app.get("/api/system/metrics")
    async def system_metrics() -> JSONResponse:
        """CPU, RAM, GPU, disk I/O, process RSS, NIC, storage."""
        return JSONResponse(col.system_payload())

    @app.get("/api/cameras/{camera_index}/stats")
    async def camera_stats(camera_index: int) -> JSONResponse:
        """Per-camera grab/detection stats (requires pipeline hooks)."""
        stats = col.camera_stats(camera_index)
        if stats is None:
            raise HTTPException(status_code=404, detail="camera_index not configured")
        return JSONResponse(stats)

    @app.websocket("/api/ws/dashboard")
    async def ws_dashboard(websocket: WebSocket) -> None:
        """Push dashboard JSON every SYSTEM_METRICS_POLL_SEC."""
        await websocket.accept()
        interval = max(0.5, settings.system_metrics_poll_sec)
        try:
            while True:
                await websocket.send_text(json.dumps(col.dashboard_payload()))
                await asyncio.sleep(interval)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("dashboard websocket closed: %s", exc)

    return app
