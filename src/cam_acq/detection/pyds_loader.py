"""Optional pyds import (DeepStream Python bindings; build per DS 9 install guide)."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

_PYDS: Any | None = None
_PYDS_TRIED = False


def _candidate_pyds_paths() -> list[str]:
    """Paths that may contain a built pyds wheel or site-packages."""
    root = os.getenv("DEEPSTREAM_ROOT", "/opt/nvidia/deepstream/deepstream")
    paths = [
        os.getenv("PYDS_PATH", "").strip(),
        str(Path(root).parent / "deepstream_python_apps" / "pyds" / "lib" / "python3.12" / "site-packages"),
        str(Path(root).parent / "deepstream_python_apps" / "bindings" / "dist"),
    ]
    return [p for p in paths if p]


def import_pyds() -> Any:
    """Return pyds module; raise ImportError when bindings are not installed."""
    global _PYDS, _PYDS_TRIED
    if _PYDS is not None:
        return _PYDS
    if _PYDS_TRIED:
        raise ImportError(
            "pyds not available; build from deepstream_python_apps/bindings (DS 9) "
            "or set PYDS_PATH to site-packages containing pyds"
        )
    _PYDS_TRIED = True
    try:
        _PYDS = importlib.import_module("pyds")
        return _PYDS
    except ImportError:
        pass
    for extra in _candidate_pyds_paths():
        if extra not in sys.path and Path(extra).is_dir():
            sys.path.insert(0, extra)
        try:
            _PYDS = importlib.import_module("pyds")
            return _PYDS
        except ImportError:
            continue
    raise ImportError(
        "pyds not available; build from deepstream_python_apps/bindings (DS 9) "
        "or set PYDS_PATH to site-packages containing pyds"
    )


def pyds_available() -> bool:
    """True when pyds can be imported."""
    try:
        import_pyds()
        return True
    except ImportError:
        return False
