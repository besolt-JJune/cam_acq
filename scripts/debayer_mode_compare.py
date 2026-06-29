#!/usr/bin/env python3
"""Compare YOLO live throughput and CPU load: cpu_sdk vs gpu_phase3."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil


def _sample_loop(samples: list[dict], stop: threading.Event, poll_sec: float) -> None:
  psutil.cpu_percent(interval=None)
  while not stop.wait(poll_sec):
    samples.append(
      {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
      }
    )


def _run_mode(*, mode: str, duration: float, root: Path) -> dict:
  env = {**os.environ, "DEBAYER_MODE": mode}
  out_json = root / f"debayer_cmp_{mode}.json"
  samples: list[dict] = []
  stop = threading.Event()
  sampler = threading.Thread(target=_sample_loop, args=(samples, stop, 1.0), daemon=True)
  sampler.start()
  t0 = time.perf_counter()
  proc = subprocess.run(
    [
      "uv",
      "run",
      "cam-acq-yolo-live",
      "--duration",
      str(duration),
      "--no-record",
      "--no-event-recording",
      "--output",
      str(out_json),
    ],
    cwd=root,
    env=env,
    capture_output=True,
    text=True,
  )
  wall = time.perf_counter() - t0
  stop.set()
  sampler.join(timeout=2.0)

  report: dict = {}
  if out_json.is_file():
    report = json.loads(out_json.read_text(encoding="utf-8"))

  cpu_vals = [s["cpu_percent"] for s in samples if s.get("cpu_percent") is not None]
  ram_vals = [s["ram_percent"] for s in samples if s.get("ram_percent") is not None]

  cams = report.get("cameras", [])
  fps_vals = [c.get("fps_pushed_avg", 0) for c in cams]
  pushed = [c.get("frames_pushed", 0) for c in cams]

  return {
    "debayer_mode": mode,
    "exit_code": proc.returncode,
    "status": report.get("status"),
    "wall_sec": round(wall, 2),
    "duration_sec": duration,
    "fps_pushed_avg_per_cam": fps_vals,
    "fps_pushed_avg_min": round(min(fps_vals), 2) if fps_vals else None,
    "frames_pushed_per_cam": pushed,
    "frames_pushed_min": min(pushed) if pushed else None,
    "cpu_percent_avg": round(sum(cpu_vals) / len(cpu_vals), 1) if cpu_vals else None,
    "cpu_percent_peak": round(max(cpu_vals), 1) if cpu_vals else None,
    "ram_percent_peak": round(max(ram_vals), 1) if ram_vals else None,
    "cpu_sample_count": len(cpu_vals),
    "stderr_tail": (proc.stderr or "")[-500:] if proc.returncode != 0 else None,
  }


def main() -> int:
  root = Path(__file__).resolve().parents[3]
  duration = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
  os.chdir(root)
  # gi/gxipy env
  venv_sh = root / "venv.sh"
  if venv_sh.is_file():
    pass  # caller should source venv.sh

  results = [_run_mode(mode=m, duration=duration, root=root) for m in ("cpu_sdk", "gpu_phase3")]
  cmp_out = {
    "schema_version": "1.0",
    "duration_sec": duration,
    "runs": results,
    "delta_fps_min": None,
    "delta_cpu_avg": None,
  }
  if len(results) == 2 and results[0]["fps_pushed_avg_min"] and results[1]["fps_pushed_avg_min"]:
    cmp_out["delta_fps_min"] = round(
      results[1]["fps_pushed_avg_min"] - results[0]["fps_pushed_avg_min"], 2
    )
  if results[0].get("cpu_percent_avg") is not None and results[1].get("cpu_percent_avg") is not None:
    cmp_out["delta_cpu_avg"] = round(results[1]["cpu_percent_avg"] - results[0]["cpu_percent_avg"], 1)

  out_path = root / "healthcheck" / "debayer_mode_compare.json"
  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_text(json.dumps(cmp_out, indent=2) + "\n", encoding="utf-8")
  print(json.dumps(cmp_out, indent=2))
  return 0 if all(r.get("status") == "PASS" for r in results) else 1


if __name__ == "__main__":
  raise SystemExit(main())
