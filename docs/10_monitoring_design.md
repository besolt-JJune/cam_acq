# Monitoring 설계 (카메라 + 호스트 리소스)

로컬 폐쇄망 Dashboard. 스트리밍 원칙은 `02_streaming_design.md`, 전체 구조는 `architecture.md`.

**구현:** `src/cam_acq/monitoring/`, CLI `cam-acq-monitoring`

## 1. 모니터 항목

### 1.1 카메라 / 파이프라인

| 항목 | 소스 | API 필드 | UI |
|------|------|----------|-----|
| 수신 FPS (1s rolling) | `GrabStats` → `PipelineHooks` | `cameras[].fps_live` | 카메라 카드 |
| 프레임 드랍 / incomplete | `GrabStats` | `frame_drops`, `incomplete_frames` | 카드 하단 |
| Detection (person 수) | `DetectionFrameEvent` → hooks | `cameras[].person_count` | 카드 (bbox overlay는 추후) |
| 녹화 상태 | `RecordingController.status_snapshot()` | `recording.state` | footer |
| Storage (`STORAGE_PATH`) | `disk_usage_at` + `StorageManager` | `system.storage` | 시스템 패널 게이지 |
| 활성 녹화 경로 | `StorageManager.location` | `system.storage.active_path` | 시스템 패널 |
| 카메라 연결 | `GrabStats.open_error` / frames | `cameras[].connection` | online/offline/unknown |
| Pre-buffer RAM | `RecordingController.memory_report()` 또는 추정 | `prebuffer.bytes_total` | 시스템 패널 |
| TimeSync drift | `SessionTimeSync` + live tick spread | `timesync.live_max_skew_us` | NIC 패널 |

녹화 상태 값: `idle` | `armed` | `post_buffer` | `ready_to_flush` | `encoding`

### 1.2 호스트 리소스

| 항목 | 수집 | API 필드 |
|------|------|----------|
| CPU | `psutil` | `system.cpu` |
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
| UI | WebSocket push | 썸네일 스트림은 `UI_MAX_DISPLAY_FPS` (추후) |

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
| 시스템 패널 | CPU·RAM·GPU·NVENC·NVDEC·VRAM·온도·RSS·disk I/O·**storage**·pre-buffer |
| 카메라 그리드 | 채널별 FPS·person·drop (썸네일/bbox overlay 추후) |
| NIC / TimeSync | `CAMERA*_INTERFACE` 트래픽·에러, live skew |

**미구현 (Phase 5 잔여):** 수동 녹화 버튼 (`POST /api/recording/trigger`), MJPEG/WebSocket 썸네일, **카메라 파라미터 설정 UI** (§3.1)

### 3.1 카메라 파라미터 설정 UI (Phase 5 — **미구현**, API만 준비)

Dashboard 메인 화면과 **분리된 설정 창**(모달 또는 별도 패널). Phase 5에서 구현 예정.

**진입**

- Dashboard 헤더/툴바에 `Camera Settings` (또는 동등) 버튼 → 설정 창 오픈

**설정 창 구성**

| 영역 | 동작 |
|------|------|
| 카메라 선택 | `connection=online` 인 채널만 선택 가능; 오프라인은 비활성 + 사유 표시 |
| 현재값 표시 | 선택 시 `GET /api/cameras/{id}/params` 로 폼 초기화 |
| 편집 필드 | ExposureTime (µs), ExposureAuto, AcquisitionFrameRate, Gain, GainAuto, GammaMode, Gamma |
| 적용 | 사용자가 **Apply** 클릭 시에만 `PATCH /api/cameras/{id}/params` 호출 (자동/주기 적용 없음) |
| 피드백 | `apply_pending` / `last_apply_error` 표시; 성공 시 GET으로 재동기화 |

**UX 원칙**

- 파라미터는 **사용자 명시 요청(PATCH) 시에만** grab 스레드가 GenICam에 반영한다. 프레임마다 재적용하지 않는다 (취득 중 이미지 깨짐 방지).
- 카메라 전환 시 미저장 편집은 확인 다이얼로그(선택).
- enum 필드(ExposureAuto, GainAuto, GammaMode)는 기기 symbolic 목록을 API 응답 또는 고정 매핑으로 드롭다운.

- **백엔드 전제**

- grab 루프와 monitoring API가 **동일 프로세스** (`cam-acq-yolo-live --with-monitoring` 등). 단독 `cam-acq-monitoring`만으로는 PATCH 불가 (`503`).

**별도 프로세스 검증 (Dashboard 전 테스트)**

Galaxy SDK는 동일 카메라를 **두 프로세스가 동시에 open 할 수 없다**. grab가 `cam` 핸들을 잡는 동안 별도 gxipy 스크립트로 `set()` 하는 방식은 불가.

대신 grab 프로세스의 REST API를 **다른 터미널/프로세스**에서 호출한다 (Dashboard와 동일 경로):

```bash
# 터미널 1 — grab + monitoring API
cam-acq-yolo-live --with-monitoring --duration 3600

# 터미널 2 — parameter client (HTTP only, 카메라 직접 open 안 함)
cam-acq-params get --camera 0
cam-acq-params patch --camera 0 --gain 8.0 --exposure-auto Off --wait
```

`cam-acq-params` = `GET/PATCH /api/cameras/{id}/params` 래퍼. `--wait`는 grab 스레드 반영·`last_apply_error` 확인용.

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
| (암묵) | FPS &lt; 22 | `camera_fps_low` |
| | drop/incomplete &gt; 0 | `camera_drops` / `camera_incomplete` |
| | offline | `camera_offline` |

## 4. API

### REST (구현됨)

```
GET  /api/health
GET  /api/system/metrics
GET  /api/cameras/{camera_index}/stats
GET  /api/cameras/{camera_index}/params
PATCH /api/cameras/{camera_index}/params
WS   /api/ws/dashboard
```

`GET/PATCH .../params` — grab 루프와 동일 프로세스 + `RuntimeParamStore` 연결 시 (`cam-acq-yolo-live --with-monitoring` 등).

- **GET** — 마지막으로 카메라에 반영된 값 (`apply_pending`, `last_apply_error` 포함).
- **PATCH** — 사용자 요청 시에만 큐잉; grab 스레드가 **다음 루프에서 신호를 받았을 때 한 번** GenICam에 반영 (프레임마다 적용하지 않음). UI는 Apply 버튼 → PATCH.

`GET /api/cameras/{id}/params` 응답 예:

```json
{
  "camera_index": 0,
  "exposure_time_us": 10000.0,
  "exposure_auto": "Off",
  "acquisition_frame_rate": 23.0,
  "gain": 10.0,
  "gain_auto": "Off",
  "gamma_mode": "User",
  "gamma": 1.0,
  "apply_pending": false,
  "last_apply_error": null
}
```

### 추후

```
GET  /api/stream/{camera_index}
POST /api/recording/trigger
```

### `GET /api/health` 최상위 블록

- `status`, `warnings`, `system` (includes `storage`), `cameras`, `recording`, `prebuffer`, `timesync`

### `GET /api/system/metrics` 예시

```json
{
  "schema_version": "1.0",
  "collected_at": "2026-06-29T12:00:00+09:00",
  "cpu": { "percent": 34.2, "count": 16 },
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
- `08_ssh_healthcheck_guide.md` — 원격 검증
- `00_project_plan.md` — Phase 5
