# Monitoring 설계 (카메라 + 호스트 리소스)

로컬 폐쇄망 Dashboard. 스트리밍 원칙은 `02_streaming_design.md`, 전체 구조는 `architecture.md`.

**구현:** `src/cam_acq/monitoring/`, CLI `cam-acq-monitoring`

## 1. 모니터 항목

### 1.1 카메라 / 파이프라인

| 항목 | 소스 | API 필드 | UI |
|------|------|----------|-----|
| 수신 FPS (1s rolling) | `GrabStats` → `PipelineHooks` | `cameras[].fps_live` | 카메라 카드 |
| 프레임 드랍 / incomplete | `GrabStats` | `frame_drops`, `incomplete_frames` | 카드 하단 |
| Detection (person 수) | `DetectionFrameEvent` → hooks | `cameras[].person_count`, `detections[]` | 카드 + bbox canvas |
| 녹화 상태 | `RecordingController` + `RecordingTrigger` | `recording.state`, `manual_active`, `manual_elapsed_sec` | footer |
| Storage (`STORAGE_PATH`) | `disk_usage_at` + `StorageManager` | `system.storage` | 시스템 패널 게이지 |
| 활성 녹화 경로 | `StorageManager.location` | `system.storage.active_path` | 시스템 패널 |
| 카메라 연결 | `GrabStats.open_error` / frames / `RecoveryStats` | `cameras[].connection`, `recovery_events` | online/offline/unknown |
| Pre-buffer RAM | `RecordingController.memory_report()` 또는 추정 | `prebuffer.bytes_total` | 시스템 패널 |
| TimeSync drift | `SessionTimeSync` + live tick spread | `timesync.live_max_skew_us` | NIC 패널 |

녹화 상태 값: `idle` | `recording` | `post_buffer` | `ready_to_flush` | `encoding`

- **수동 녹화 중:** `recording (manual) · M:SS` (footer, `manual_elapsed_sec` from WebSocket)
- **Event 침묵 tail:** `post_buffer` (person 무검출 후 `RECORDING_BUFFER_SEC` 대기)

### 1.2 호스트 리소스

| 항목 | 수집 | API 필드 |
|------|------|----------|
| CPU | `psutil` + thermal sysfs | `system.cpu` (`temperature_c`) |
| RAM | `psutil` | `system.memory` |
| GPU SM | NVML | `system.gpu.utilization_percent` |
| NVENC / NVDEC | NVML encoder/decoder util | `system.gpu.encoder_percent`, `decoder_percent` |
| VRAM / 온도 / 전력 | NVML | `system.gpu.*` |
| 프로세스 RSS | `psutil.Process()` | `system.process.rss_bytes` |
| 디스크 I/O | `psutil.disk_io_counters` (rate) | `system.disk_io` |
| GigE NIC | `psutil.net_io_counters(pernic)` on `CAMERA*_INTERFACE` | `system.network[]` |

### 1.3 수집 주기

| 스트림 | 주기 | 비고 |
|--------|------|------|
| 호스트 메트릭 | `SYSTEM_METRICS_POLL_SEC` (기본 2s) | `HostMetricsSampler` daemon |
| 카메라 FPS | 1s rolling (`GrabStats._fps_window`) | grab 루프가 hooks 갱신 시 |
| UI | WebSocket push + MJPEG | YOLO input resize RGB (`gst_thumb` probe / `push_batch`) |

## 2. Data Collector

```
[Grab / YOLO / Recording / TimeSync]
        │  PipelineHooks (in-process)
        ▼
  DashboardCollector
        │     HostMetricsSampler (thread): CPU, RAM, GPU, disk_io, RSS, NIC
        │     disk_usage_at(STORAGE_PATH) + StorageManager active path
        ▼
  aggregate JSON snapshot
        ▼
  FastAPI → REST + WebSocket
```

### PipelineHooks 연동 (통합 앱 / record_test)

```python
from cam_acq.monitoring import DashboardCollector, PipelineHooks

hooks = PipelineHooks()
collector = DashboardCollector(settings, hooks=hooks)

# 세션 시작
hooks.bind_time_sync(time_sync)
hooks.bind_recording(controller, trigger=recording_trigger)

# grab 루프 (주기적)
hooks.set_grab_stats(grab_stats)

# YOLO probe
hooks.set_detection(detection_frame_event)
```

파이프라인 미연결 시: 카메라 슬롯은 `.env` 기준 placeholder, `connection=unknown`, pre-buffer는 용량 **추정**.

## 3. Dashboard UI

`http://localhost:{MONITORING_WEB_PORT}` (`MONITORING_WEB_PORT` 기본 8080)

| 영역 | 내용 |
|------|------|
| 시스템 패널 | CPU·RAM·GPU·NVENC·NVDEC·VRAM·**CPU/GPU 온도(한 행)**·RSS·disk I/O·**storage**·pre-buffer |
| 카메라 그리드 | 채널별 FPS·person·drop·MJPEG 썸네일·bbox overlay |
| NIC / TimeSync | `CAMERA*_INTERFACE` 트래픽·에러, live skew |

**구현 완료.** 파이프라인 연동은 `cam-acq-yolo-live --with-monitoring` 또는 `cam-acq-record-test --with-monitoring`.

Dashboard 헤더 **● REC** / **■ STOP** → `POST /api/recording/trigger` (start) · `POST /api/recording/stop` (end).  
수동 녹화 중 footer에 `recording (manual) · M:SS` 표시 (`manual_elapsed_sec`).

### 3.1 카메라 파라미터 설정 UI (Phase 5)

Dashboard 헤더 **Camera Settings** → 모달에서 online 채널만 선택, **Apply** → `PATCH /api/cameras/{id}/params`.

### 경고 임계치 (`.env`)

| 변수 | 기본 | health 경고 |
|------|------|-------------|
| `CPU_WARN_PERCENT` | 85 | `cpu_high` |
| `RAM_WARN_PERCENT` | 85 | `ram_high` |
| `GPU_UTIL_WARN_PERCENT` | 90 | `gpu_util_high` |
| `GPU_TEMP_WARN_C` | 80 | `gpu_temp_warn` |
| `GPU_TEMP_CRITICAL_C` | 90 | `gpu_temp_critical` → **FAIL** |
| `STORAGE_FULL_PERCENTAGE` | 90 | `storage_high` |
| `CROSS_CAMERA_SKEW_TOLERANCE_MS` | 50 | `timesync_skew` |
| (암묵) | FPS &lt; 0.85× nominal (3ch headroom) | `camera_fps_low` |
| | drop/incomplete &gt; 0 | `camera_drops` / `camera_incomplete` |
| | offline | `camera_offline` |

### 1.4 GigE disconnect / reconnect (구현됨)

운영 스펙: `13_gige_disconnect_recovery.md` §3. E2E: `11_field_pending_work.md` §2.3.

- disconnect: `connection=offline`, `recovery_events++`, network 패널 recovery 카운터
- reconnect (프로세스 재시작 없이): `connection=online`, MJPEG·FPS 복구, `reconnect_success++`
- 녹화 중: `split.reason: gige_disconnect` on closed seg; reconnect 후 새 seg 파일

## 4. API

### REST (구현됨)

```
GET  /api/health
GET  /api/system/metrics
GET  /api/cameras/{camera_index}/stats
GET  /api/cameras/{camera_index}/params
PATCH /api/cameras/{camera_index}/params
POST /api/recording/trigger        # manual start
POST /api/recording/stop           # manual stop
GET  /api/stream/{camera_index}       # MJPEG multipart live
GET  /api/snapshot/{camera_index}     # single JPEG (curl -o cam0.jpg)
WS   /api/ws/dashboard
```

`--with-monitoring` 시 pre-buffer·수동 REC·스트림·params 사용 가능. 단독 `cam-acq-monitoring`은 호스트 메트릭만 (REC/스트림 `503`).

### `GET /api/health` 최상위 블록

- `status`, `warnings`, `system` (includes `storage`), `cameras`, `recording`, `prebuffer`, `timesync`

### `GET /api/system/metrics` 예시

```json
{
  "schema_version": "1.0",
  "collected_at": "2026-06-29T12:00:00+09:00",
  "cpu": { "percent": 34.2, "count": 16, "temperature_c": 58.0 },
  "memory": { "percent": 61.5, "used_bytes": 20615843020, "total_bytes": 33554432000 },
  "gpu": {
    "utilization_percent": 72,
    "encoder_percent": 45,
    "decoder_percent": 2,
    "memory_used_mb": 8192,
    "memory_total_mb": 16384,
    "temperature_c": 62
  },
  "disk_io": { "read_bytes_per_sec": 1048576, "write_bytes_per_sec": 5242880 },
  "process": { "pid": 12345, "rss_bytes": 536870912 },
  "network": [
    { "name": "enp22s0", "bytes_recv_per_sec": 120000000, "bytes_sent_per_sec": 500000, "errin": 0 }
  ],
  "storage": {
    "path": "/data/recordings",
    "percent": 42.1,
    "free_bytes": 193273528320,
    "accessible": true,
    "active_path": "/data/recordings",
    "active_is_fallback": false,
    "warn_percent": 90
  }
}
```

### `system.storage` 필드

- `path` — `STORAGE_PATH` (용량 조회 대상)
- `percent`, `used_bytes`, `free_bytes`, `total_bytes`, `accessible`
- `active_path`, `active_is_fallback`, `primary_reject_reason` — 실제 녹화 경로
- `management`, `warn_percent`

## 5. SSH / 원격 확인

```bash
uv run cam-acq-monitoring   # 또는 nohup

curl -s localhost:8080/api/health | jq
curl -s localhost:8080/api/system/metrics | jq '.cpu,.memory,.gpu,.disk_io'
curl -s localhost:8080/api/health | jq '.system.storage,.recording,.timesync'
curl -s localhost:8080/api/cameras/0/stats | jq
curl -s -X POST localhost:8080/api/recording/trigger | jq
curl -s -X POST localhost:8080/api/recording/stop | jq
curl -s localhost:8080/api/snapshot/0 -o /tmp/cam0.jpg && file /tmp/cam0.jpg
# MJPEG는 multipart — 브라우저/img 태그용. 단일 파일은 snapshot 사용.
```

원격 브라우저: SSH `-L 8080:localhost:8080` 또는 Cursor Ports (`08_ssh_healthcheck_guide.md`).

## 6. 의존성

| 패키지 | 용도 |
|--------|------|
| `fastapi`, `uvicorn` | HTTP + WebSocket |
| `psutil` | CPU, RAM, disk_io, process, NIC |
| `nvidia-ml-py` (`pynvml`) | GPU, NVENC/NVDEC, VRAM, temp |

## 7. 관련 문서

- `02_streaming_design.md` — FPS, 포트, 스트림
- `13_gige_disconnect_recovery.md` — disconnect 시 dashboard·recording 동작 스펙
- `08_ssh_healthcheck_guide.md` — 원격 검증
- `00_project_plan.md` — Phase 5
