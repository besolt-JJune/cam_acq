"""Load .env settings and camera list (camera_index 0-based)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Nominal camera FPS for healthcheck frame-count threshold.
NOMINAL_FPS = 23.0


def project_root() -> Path:
    """Repository root (parent of src/)."""
    return Path(__file__).resolve().parents[2]


def setup_galaxy_lib_path() -> Path:
    """Prepend Galaxy C SDK lib to LD_LIBRARY_PATH; return lib directory."""
    lib = project_root() / "sdk" / "Galaxy_camera" / "c" / "lib" / "x86_64"
    if not lib.is_dir():
        raise FileNotFoundError(f"Galaxy SDK lib not found: {lib}")
    prev = os.environ.get("LD_LIBRARY_PATH", "")
    lib_str = str(lib)
    if lib_str not in prev.split(":"):
        os.environ["LD_LIBRARY_PATH"] = f"{lib_str}:{prev}" if prev else lib_str
    return lib


def load_env(env_file: Path | None = None) -> None:
    """Load .env from explicit path, project root, or cwd."""
    if env_file and env_file.is_file():
        load_dotenv(env_file)
        return
    for candidate in (project_root() / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            load_dotenv(candidate)
            return


@dataclass(frozen=True)
class CameraEndpoint:
    """One camera slot: index, IP, optional bind interface name."""

    index: int
    ip: str
    interface: str | None = None


@dataclass(frozen=True)
class Settings:
    """Application settings from environment."""

    num_cameras: int
    cameras: tuple[CameraEndpoint, ...]
    log_path: Path
    healthcheck_output_dir: Path
    pixel_format: str
    camera_width: int
    camera_height: int
    timestamp_reset_on_session: bool
    cross_camera_skew_tolerance_ms: int

    @property
    def camera_ips(self) -> list[str]:
        return [c.ip for c in self.cameras]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def load_settings(env_file: Path | None = None) -> Settings:
    """Parse .env into Settings; raises if camera IPs missing."""
    load_env(env_file)
    num = _env_int("NUM_CAMERAS", 1)
    cameras: list[CameraEndpoint] = []
    for i in range(num):
        ip = os.getenv(f"CAMERA{i}_IP", "").strip()
        if not ip:
            raise ValueError(f"CAMERA{i}_IP is required (NUM_CAMERAS={num})")
        iface = os.getenv(f"CAMERA{i}_INTERFACE", "").strip() or None
        cameras.append(CameraEndpoint(index=i, ip=ip, interface=iface))

    log_path = Path(os.getenv("LOG_PATH", "./logs"))
    hc_dir = Path(os.getenv("HEALTHCHECK_OUTPUT_DIR", log_path / "healthcheck"))

    return Settings(
        num_cameras=num,
        cameras=tuple(cameras),
        log_path=log_path,
        healthcheck_output_dir=hc_dir,
        pixel_format=os.getenv("PIXEL_FORMAT", "BayerRG8"),
        camera_width=_env_int("CAMERA_WIDTH", 0),
        camera_height=_env_int("CAMERA_HEIGHT", 0),
        timestamp_reset_on_session=_env_bool("TIMESTAMP_RESET_ON_SESSION", True),
        cross_camera_skew_tolerance_ms=_env_int("CROSS_CAMERA_SKEW_TOLERANCE_MS", 50),
    )


def ensure_dir(path: Path) -> Path:
    """Create directory if possible; fall back to ./logs on permission error."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = project_root() / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
