"""Recording path selection (primary/fallback) and FIFO cleanup."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class StorageLocation:
    """Resolved writable storage root."""

    path: Path
    is_fallback: bool


@dataclass(frozen=True)
class PathDiskUsage:
    """Filesystem usage for a configured path (typically STORAGE_PATH)."""

    path: Path
    percent: float | None
    used_bytes: int | None
    free_bytes: int | None
    total_bytes: int | None
    accessible: bool
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize for monitoring API responses."""
        return {
            "path": str(self.path),
            "percent": self.percent,
            "used_bytes": self.used_bytes,
            "free_bytes": self.free_bytes,
            "total_bytes": self.total_bytes,
            "accessible": self.accessible,
            "error": self.error,
        }


def disk_usage_at(path: Path) -> PathDiskUsage:
    """Return mount usage for ``path``; does not create directories or probe fallback."""
    try:
        usage = shutil.disk_usage(path)
        pct = (usage.used / usage.total * 100.0) if usage.total else None
        return PathDiskUsage(
            path=path,
            percent=pct,
            used_bytes=usage.used,
            free_bytes=usage.free,
            total_bytes=usage.total,
            accessible=True,
        )
    except OSError as exc:
        return PathDiskUsage(
            path=path,
            percent=None,
            used_bytes=None,
            free_bytes=None,
            total_bytes=None,
            accessible=False,
            error=f"{type(exc).__name__}: {exc}",
        )


class StorageManager:
    """Pick STORAGE_PATH or STORAGE_PATH_SUB; optional FIFO delete by age."""

    def __init__(
        self,
        primary: Path,
        fallback: Path,
        *,
        management: str = "FIFO_DELETE",
        full_percentage: int = 90,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._management = management.upper()
        self._full_percentage = full_percentage
        self._primary_reject_reason: str | None = None
        self._location = self._resolve()

    @property
    def location(self) -> StorageLocation:
        return self._location

    @property
    def primary_reject_reason(self) -> str | None:
        """Why primary was skipped; None if primary is active or not yet resolved."""
        return self._primary_reject_reason

    def _resolve(self) -> StorageLocation:
        for path, is_fallback in ((self._primary, False), (self._fallback, True)):
            try:
                path.mkdir(parents=True, exist_ok=True)
                test = path / ".cam_acq_write_test"
                test.write_text("ok", encoding="utf-8")
                test.unlink()
                return StorageLocation(path=path, is_fallback=is_fallback)
            except OSError as exc:
                if not is_fallback:
                    self._primary_reject_reason = _primary_reject_message(path, exc)
                continue
        raise OSError(f"no writable storage: {self._primary} or {self._fallback}")

    def usage_ratio(self) -> float:
        """Fraction of filesystem used (0..1) for active path."""
        usage = shutil.disk_usage(self._location.path)
        return usage.used / usage.total if usage.total else 1.0

    def maybe_fifo_cleanup(self) -> int:
        """Delete oldest recording artifacts when over threshold; return files removed."""
        if self._management != "FIFO_DELETE":
            return 0
        if self.usage_ratio() * 100 < self._full_percentage:
            return 0
        root = self._location.path
        candidates: list[tuple[float, Path]] = []
        for pattern in ("*.mp4", "*.json", "*.jsonl"):
            for p in root.glob(pattern):
                candidates.append((p.stat().st_mtime, p))
        candidates.sort(key=lambda x: x[0])
        removed = 0
        for _, path in candidates:
            if self.usage_ratio() * 100 < self._full_percentage:
                break
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
        return removed

    def make_basename(self, *, camera_index: int, segment_index: int, when: float | None = None) -> str:
        """Timestamped basename without extension; ``when`` is POSIX epoch seconds (shared across cameras)."""
        ts = datetime.fromtimestamp(when or time.time()).strftime("%Y%m%d_%H%M%S")
        return f"{ts}_cam{camera_index}_seg{segment_index:02d}"

    def segment_paths(self, basename: str) -> dict[str, Path]:
        """mp4/json/jsonl paths under active storage."""
        root = self._location.path
        return {
            "video": root / f"{basename}.mp4",
            "session": root / f"{basename}.json",
            "frames": root / f"{basename}.frames.jsonl",
        }


def _primary_reject_message(path: Path, exc: OSError) -> str:
    """Human-readable primary failure; hint when group membership is stale in this shell."""
    msg = f"{type(exc).__name__}: {exc}"
    if exc.errno != 13:
        return msg
    return (
        f"{msg} — on mergerfs, supplementary groups may not apply until "
        f"`sudo mount -o remount {path.parent}` or setfacl for your user; "
        f"try: sg $(stat -c %G {path}) -c 'touch {path}/.test'"
    )
