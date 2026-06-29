"""FastAPI monitoring server: REST, WebSocket, static dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from cam_acq.camera.params import patch_to_param_dict
from cam_acq.config import Settings
from cam_acq.monitoring.collector import DashboardCollector
from cam_acq.monitoring.thumbnails import placeholder_jpeg

logger = logging.getLogger(__name__)
_STATIC_DIR = Path(__file__).resolve().parent / "static"


class CameraParamsUpdate(BaseModel):
    """Partial GenICam parameter update (PATCH body)."""

    model_config = ConfigDict(extra="forbid")

    exposure_time_us: float | None = None
    exposure_auto: str | None = None
    acquisition_frame_rate: float | None = None
    gain: float | None = None
    gain_auto: str | None = None
    gamma_mode: str | None = None
    gamma: float | None = None


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

    @app.get("/api/cameras/{camera_index}/params")
    async def camera_params_get(camera_index: int) -> JSONResponse:
        """Current GenICam parameters (last applied by grab thread)."""
        store = col.hooks.param_store
        if store is None:
            raise HTTPException(status_code=503, detail="parameter control not enabled")
        if not store.is_configured(camera_index):
            raise HTTPException(status_code=404, detail="camera_index not configured")
        body = store.snapshot(camera_index)
        if body is None:
            raise HTTPException(status_code=404, detail="camera_index not configured")
        return JSONResponse(body)

    @app.patch("/api/cameras/{camera_index}/params")
    async def camera_params_patch(
        camera_index: int,
        update: CameraParamsUpdate,
    ) -> JSONResponse:
        """Queue parameter apply on user request (grab thread applies once, not every frame)."""
        store = col.hooks.param_store
        if store is None:
            raise HTTPException(status_code=503, detail="parameter control not enabled")
        if not store.is_configured(camera_index):
            raise HTTPException(status_code=404, detail="camera_index not configured")
        changes = patch_to_param_dict(update.model_dump())
        if not changes:
            raise HTTPException(status_code=400, detail="no parameter fields in body")
        try:
            store.queue_update(camera_index, changes)
        except KeyError:
            raise HTTPException(status_code=404, detail="camera_index not configured") from None
        body = store.snapshot(camera_index)
        return JSONResponse(body or {"camera_index": camera_index})

    @app.post("/api/recording/trigger")
    async def recording_trigger() -> JSONResponse:
        """Start manual all-channel recording (until POST /api/recording/stop)."""
        try:
            decision = col.manual_recording_start()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "trigger": decision})

    @app.post("/api/recording/stop")
    async def recording_stop() -> JSONResponse:
        """End manual recording session."""
        try:
            body = col.manual_recording_stop()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JSONResponse(body)

    @app.get("/api/snapshot/{camera_index}")
    async def camera_snapshot(camera_index: int) -> Response:
        """Single JPEG frame (RESIZE_WIDTH×HEIGHT). Use this for curl/file save."""
        if col.camera_stats(camera_index) is None:
            raise HTTPException(status_code=404, detail="camera_index not configured")
        jpeg = col.hooks.thumbnails.get_jpeg(camera_index)
        if not jpeg:
            raise HTTPException(status_code=503, detail="no frame yet")
        return Response(content=jpeg, media_type="image/jpeg")

    @app.get("/api/stream/{camera_index}")
    async def camera_stream(camera_index: int) -> StreamingResponse:
        """MJPEG live stream (multipart; not a single JPEG file — use /api/snapshot for curl)."""
        if col.camera_stats(camera_index) is None:
            raise HTTPException(status_code=404, detail="camera_index not configured")

        boundary = b"--frame"
        interval = max(1.0 / max(1, settings.ui_max_display_fps), 0.05)

        async def _frames():
            while True:
                jpeg = col.hooks.thumbnails.get_jpeg(camera_index) or placeholder_jpeg()
                yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(interval)

        return StreamingResponse(
            _frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

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
