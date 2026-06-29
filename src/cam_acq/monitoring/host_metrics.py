"""Host CPU/RAM/GPU sampling via psutil and NVML (pynvml)."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class CpuMetrics:
    """CPU utilization snapshot."""

    percent: float | None
    count: int | None
    temperature_c: float | None = None


@dataclass(frozen=True)
class MemoryMetrics:
    """RAM usage snapshot."""

    percent: float | None
    used_bytes: int | None
    total_bytes: int | None


@dataclass(frozen=True)
class GpuMetrics:
    """Single-GPU NVML snapshot; fields null when NVML unavailable."""

    index: int | None
    name: str | None
    utilization_percent: float | None
    encoder_percent: float | None
    decoder_percent: float | None
    memory_used_mb: int | None
    memory_total_mb: int | None
    temperature_c: int | None
    power_w: float | None


@dataclass(frozen=True)
class DiskIoMetrics:
    """Disk read/write rates (bytes/sec) since previous sample."""

    read_bytes_per_sec: float | None
    write_bytes_per_sec: float | None


@dataclass(frozen=True)
class ProcessMetrics:
    """Current cam_acq process RSS."""

    pid: int | None
    rss_bytes: int | None


@dataclass(frozen=True)
class NetworkInterfaceMetrics:
    """Per-interface traffic since previous sample."""

    name: str
    bytes_sent_per_sec: float | None
    bytes_recv_per_sec: float | None
    errin: int | None
    errout: int | None
    dropin: int | None
    dropout: int | None


@dataclass(frozen=True)
class SystemMetricsSnapshot:
    """REST/WebSocket system metrics block."""

    schema_version: str
    collected_at: str
    cpu: CpuMetrics
    memory: MemoryMetrics
    gpu: GpuMetrics | None
    disk_io: DiskIoMetrics | None = None
    process: ProcessMetrics | None = None
    network: tuple[NetworkInterfaceMetrics, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON responses."""
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "collected_at": self.collected_at,
            "cpu": asdict(self.cpu),
            "memory": asdict(self.memory),
        }
        if self.gpu is not None:
            out["gpu"] = asdict(self.gpu)
        if self.disk_io is not None:
            out["disk_io"] = asdict(self.disk_io)
        if self.process is not None:
            out["process"] = asdict(self.process)
        if self.network:
            out["network"] = [asdict(n) for n in self.network]
        return out


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _sample_cpu() -> CpuMetrics:
    """Read CPU percent, core count, and best-effort package temperature."""
    try:
        return CpuMetrics(
            percent=psutil.cpu_percent(interval=None),
            count=psutil.cpu_count(),
            temperature_c=_sample_cpu_temperature(),
        )
    except Exception as exc:
        logger.warning("cpu sample failed: %s", exc)
        return CpuMetrics(percent=None, count=None, temperature_c=None)


def _sample_cpu_temperature() -> float | None:
    """CPU package temp via psutil sensors, else Linux thermal sysfs."""
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        temps = {}
    preferred = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")
    for name in preferred:
        if name in temps:
            vals = [e.current for e in temps[name] if e.current is not None]
            if vals:
                return float(max(vals))
    for entries in temps.values():
        vals = [e.current for e in entries if e.current is not None]
        if vals:
            return float(max(vals))
    # ponytail: sysfs scan when lm-sensors/psutil has no labels (headless)
    try:
        best: float | None = None
        for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
            temp_file = zone / "temp"
            if not temp_file.is_file():
                continue
            label = ""
            type_file = zone / "type"
            if type_file.is_file():
                label = type_file.read_text(encoding="ascii", errors="replace").strip().lower()
            t = int(temp_file.read_text(encoding="ascii").strip()) / 1000.0
            if any(k in label for k in ("cpu", "core", "package", "x86")):
                return t
            if best is None or t > best:
                best = t
        return best
    except Exception as exc:
        logger.debug("cpu temperature sysfs failed: %s", exc)
        return None


def _sample_memory() -> MemoryMetrics:
    """Read RAM used/total via psutil."""
    try:
        vm = psutil.virtual_memory()
        return MemoryMetrics(
            percent=vm.percent,
            used_bytes=vm.used,
            total_bytes=vm.total,
        )
    except Exception as exc:
        logger.warning("memory sample failed: %s", exc)
        return MemoryMetrics(percent=None, used_bytes=None, total_bytes=None)


class _NvmlReader:
    """Lazy NVML init; all reads return None on failure."""

    def __init__(self, gpu_index: int) -> None:
        self._gpu_index = gpu_index
        self._handle: Any = None
        self._pynvml: Any = None
        self._init()

    def _init(self) -> None:
        try:
            import pynvml

            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self._gpu_index)
        except Exception as exc:
            logger.warning("NVML init failed (GPU metrics disabled): %s", exc)
            self._pynvml = None
            self._handle = None

    def sample(self) -> GpuMetrics | None:
        """Return GPU metrics or None when NVML is unavailable."""
        if self._pynvml is None or self._handle is None:
            return None
        nvml = self._pynvml
        handle = self._handle
        try:
            util = nvml.nvmlDeviceGetUtilizationRates(handle)
            mem = nvml.nvmlDeviceGetMemoryInfo(handle)
            temp = nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU)
            name = nvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            power_w: float | None = None
            enc_pct: float | None = None
            dec_pct: float | None = None
            try:
                power_w = float(nvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0
            except Exception:
                pass
            try:
                enc_pct = float(nvml.nvmlDeviceGetEncoderUtilization(handle)[0])
            except Exception:
                pass
            try:
                dec_pct = float(nvml.nvmlDeviceGetDecoderUtilization(handle)[0])
            except Exception:
                pass
            return GpuMetrics(
                index=self._gpu_index,
                name=name,
                utilization_percent=float(util.gpu),
                encoder_percent=enc_pct,
                decoder_percent=dec_pct,
                memory_used_mb=int(mem.used // (1024 * 1024)),
                memory_total_mb=int(mem.total // (1024 * 1024)),
                temperature_c=int(temp),
                power_w=power_w,
            )
        except Exception as exc:
            logger.warning("gpu sample failed: %s", exc)
            return GpuMetrics(
                index=self._gpu_index,
                name=None,
                utilization_percent=None,
                encoder_percent=None,
                decoder_percent=None,
                memory_used_mb=None,
                memory_total_mb=None,
                temperature_c=None,
                power_w=None,
            )


def _sample_process() -> ProcessMetrics:
    """RSS for current process."""
    try:
        proc = psutil.Process()
        return ProcessMetrics(pid=proc.pid, rss_bytes=proc.memory_info().rss)
    except Exception as exc:
        logger.warning("process sample failed: %s", exc)
        return ProcessMetrics(pid=None, rss_bytes=None)


def _rate(prev: int | None, cur: int, dt: float) -> float | None:
    if prev is None or dt <= 0:
        return None
    return max(0.0, (cur - prev) / dt)


class HostMetricsSampler:
    """Background daemon thread that caches the latest host metrics snapshot."""

    def __init__(
        self,
        *,
        gpu_index: int = 0,
        poll_sec: float = 2.0,
        network_interfaces: tuple[str, ...] = (),
    ) -> None:
        self._gpu_index = gpu_index
        self._poll_sec = max(0.5, poll_sec)
        self._network_ifaces = tuple(i for i in network_interfaces if i)
        self._nvml = _NvmlReader(gpu_index)
        self._lock = threading.Lock()
        self._latest = self._empty_snapshot()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prev_disk: Any = None
        self._prev_net: dict[str, Any] = {}
        self._prev_sample_mono: float | None = None
        psutil.cpu_percent(interval=None)

    def _empty_snapshot(self) -> SystemMetricsSnapshot:
        return SystemMetricsSnapshot(
            schema_version=SCHEMA_VERSION,
            collected_at=_iso_now(),
            cpu=CpuMetrics(percent=None, count=None),
            memory=MemoryMetrics(percent=None, used_bytes=None, total_bytes=None),
            gpu=None,
        )

    def _sample_disk_io(self, dt: float) -> DiskIoMetrics | None:
        try:
            cur = psutil.disk_io_counters()
            if cur is None:
                return None
            read_rate = _rate(
                self._prev_disk.read_bytes if self._prev_disk else None,
                cur.read_bytes,
                dt,
            )
            write_rate = _rate(
                self._prev_disk.write_bytes if self._prev_disk else None,
                cur.write_bytes,
                dt,
            )
            self._prev_disk = cur
            return DiskIoMetrics(read_bytes_per_sec=read_rate, write_bytes_per_sec=write_rate)
        except Exception as exc:
            logger.warning("disk_io sample failed: %s", exc)
            return None

    def _sample_network(self, dt: float) -> tuple[NetworkInterfaceMetrics, ...]:
        if not self._network_ifaces:
            return ()
        try:
            pernic = psutil.net_io_counters(pernic=True)
            out: list[NetworkInterfaceMetrics] = []
            for name in self._network_ifaces:
                cur = pernic.get(name)
                if cur is None:
                    out.append(
                        NetworkInterfaceMetrics(
                            name=name,
                            bytes_sent_per_sec=None,
                            bytes_recv_per_sec=None,
                            errin=None,
                            errout=None,
                            dropin=None,
                            dropout=None,
                        )
                    )
                    continue
                prev = self._prev_net.get(name)
                sent = _rate(prev.bytes_sent if prev else None, cur.bytes_sent, dt)
                recv = _rate(prev.bytes_recv if prev else None, cur.bytes_recv, dt)
                self._prev_net[name] = cur
                out.append(
                    NetworkInterfaceMetrics(
                        name=name,
                        bytes_sent_per_sec=sent,
                        bytes_recv_per_sec=recv,
                        errin=cur.errin,
                        errout=cur.errout,
                        dropin=cur.dropin,
                        dropout=cur.dropout,
                    )
                )
            return tuple(out)
        except Exception as exc:
            logger.warning("network sample failed: %s", exc)
            return ()

    def sample_once(self) -> SystemMetricsSnapshot:
        """Take one synchronous sample (used by tests and first poll)."""
        now = time.monotonic()
        dt = (now - self._prev_sample_mono) if self._prev_sample_mono is not None else self._poll_sec
        self._prev_sample_mono = now

        cpu = _sample_cpu()
        memory = _sample_memory()
        gpu = self._nvml.sample()
        disk_io = self._sample_disk_io(dt)
        process = _sample_process()
        network = self._sample_network(dt)
        return SystemMetricsSnapshot(
            schema_version=SCHEMA_VERSION,
            collected_at=_iso_now(),
            cpu=cpu,
            memory=memory,
            gpu=gpu,
            disk_io=disk_io,
            process=process,
            network=network,
        )

    def snapshot(self) -> SystemMetricsSnapshot:
        """Return the latest cached snapshot from the background thread."""
        with self._lock:
            return self._latest

    def start(self) -> None:
        """Start the background polling thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        with self._lock:
            self._latest = self.sample_once()
        self._thread = threading.Thread(target=self._run, name="host-metrics", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to exit."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_sec + 1.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            snap = self.sample_once()
            with self._lock:
                self._latest = snap
            self._stop.wait(self._poll_sec)
