"""Daily log file under LOG_PATH."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from cam_acq.config import ensure_dir


def setup_logging(log_dir: Path, name: str = "cam_acq") -> logging.Logger:
    """Attach file (YYYY-MM-DD.log) and stderr handlers; return named logger."""
    log_dir = ensure_dir(log_dir)
    log_file = log_dir / f"{date.today().isoformat()}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger
