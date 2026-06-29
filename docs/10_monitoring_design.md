# Monitoring 설계 (카메라 + 호스트 리소스)

로컬 폐쇄망 Dashboard. 스트리밍 원칙은 `02_streaming_design.md`, 전체 구조는 `architecture.md`.

## 1. 모니터 항목

### 1.1 카메라 / 파이프라인 (기존)

| 항목 | 소스 | UI 표시 |
|------|------|---------|
| 수신 FPS (채널별) | Grab / Collector | 채널 카드, 숫자 + 미니 스파크라인 |
| 프레임 드랍 / incomplete | healthcheck 동일 기준 | 채널 상태 배지 |
| Detection (person 수, bbox) | YOLO nvinfer meta | 썸네일 overlay |
| 녹화 상태 | RecordingController | REC / idle |
| Storage 사용률 | StorageManager | 게이지 + 활성 경로(`STORAGE_PATH` 또는 fallback) 여유 GB |
| 카메라 연결 | CameraManager | online / offline |

### 1.2 호스트 리소스 (추가)

| 항목 | 단위 | 수집 | UI 표시 |
|------|------|------|---------|
| **CPU 사용률** | % (전체 + 코어별 optional) | `/proc` 또는 `psutil` | 게이지, 1s~2s 갱신 |
| **메모리** | % used, used/total GB | `psutil` / `/proc/meminfo` | 게이지 + 수치 |
| **GPU 사용률** | % SM / encoder / decoder | NVML (`pynvml`) | 게이지 (연산 vs NVENC 구분 optional) |
| **GPU 메모리** | used/total MB | NVML | 바 + 수치 (16GB VRAM 모니터) |
| **GPU 온도** | °C | NVML `temperature.gpu` | 숫자 + 색상 경고 |
| **GPU 전력** | W (optional) | NVML | 숫자 (있을 때만) |

Pre-buffer RAM·3ch NVENC 부하 확인용. Phase 4~5 soak 시 **CPU/RAM/GPU/온도**를 함께 본다.

### 1.3 수집 주기

| 스트림 | 주기 | 비고 |
|--------|------|------|
| 호스트 메트릭 | `SYSTEM_METRICS_POLL_SEC` (기본 2s) | NVML 호출 최소화 |
| 카메라 FPS 통계 | 1s rolling | Collector 내부 |
| UI 렌더 | ≤ `UI_MAX_DISPLAY_FPS` | 메트릭은 WebSocket push, 영상만 FPS cap |

## 2. Data Collector 확장

```
[Grab / YOLO / Storage / Recording]
        │
        ▼
  Data Collector (in-process)
        │                    ┌─ HostMetricsSampler (thread)
        │                    │    psutil → CPU, RAM
        │                    │    pynvml → GPU util, VRAM, temp
        ▼                    └──────────┘
  aggregate snapshot (JSON)
        │
        ▼
  FastAPI  →  REST + WebSocket
```

- `HostMetricsSampler`: 별도 daemon thread, 실패 시 필드 `null` + 로그 (파이프라인 중단 없음)
- GPU 미탐지 시 GPU 필드만 비활성; CPU/RAM은 계속 수집

## 3. Dashboard UI (Phase 5)

로컬 브라우저 `http://localhost:{MONITORING_WEB_PORT}`. 단일 페이지.

### 3.1 레이아웃

```
┌─────────────────────────────────────────────────────────────┐
│  cam_acq Dashboard          [시스템 OK ▼]  [수동 녹화]        │
├──────────────────┬──────────────────────────────────────────┤
│  시스템 리소스    │  카메라 0    카메라 1    카메라 2  (4ch max) │
│  CPU      [===]  │  [썸네일]    [썸네일]    [썸네일]          │
│  RAM      [===]  │  22.7 fps    22.5 fps    — fps           │
│  GPU      [===]  │  ● online    ● online    ○ offline       │
│  VRAM     [===]  │  [det bbox]  [det bbox]  —              │
│  GPU 62°C        │                                          │
├──────────────────┴──────────────────────────────────────────┤
│  Storage: 42% (180GB free) @ /data/recordings   Recording: idle   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 UI 요구사항

| 영역 | 요구 |
|------|------|
| **시스템 패널** | CPU·RAM·GPU·VRAM·GPU 온도 항상 표시; 임계치 초과 시 색상 (warn/critical) |
| **카메라 그리드** | resize 썸네일 + FPS + 연결 상태 + detection overlay |
| **상태 요약** | storage, 녹화, 전체 health (PASS/DEGRADED/FAIL) |
| **수동 녹화** | 버튼 → 3채널 동시 trigger (`POST /api/recording/trigger`) |
| **갱신** | `WebSocket /api/ws/dashboard` 로 메트릭·상태 push; 스트림은 MJPEG/WS 별도 |
| **접근** | 로컬 전용; 인증은 Phase 5 후 필요 시 추가 |

### 3.3 경고 임계치 (`.env`)

| 변수 | 기본 | UI 동작 |
|------|------|---------|
| `CPU_WARN_PERCENT` | 85 | 게이지 주황 |
| `RAM_WARN_PERCENT` | 85 | 게이지 주황 |
| `GPU_UTIL_WARN_PERCENT` | 90 | 게이지 주황 |
| `GPU_TEMP_WARN_C` | 80 | 온도 주황 |
| `GPU_TEMP_CRITICAL_C` | 90 | 온도 빨강 + 요약 배지 |

## 4. API (예정)

### REST

```
GET  /api/health                      # grab healthcheck 지표 + 시스템 요약
GET  /api/system/metrics              # CPU, RAM, GPU 상세 스냅샷
GET  /api/cameras/{camera_index}/stats
GET  /api/stream/{camera_index}       # MJPEG or WebSocket
POST /api/recording/trigger           # 수동 녹화
```

### `GET /api/system/metrics` 응답 예시

```json
{
  "schema_version": "1.0",
  "collected_at": "2026-06-29T12:00:00+09:00",
  "cpu": {
    "percent": 34.2,
    "count": 16
  },
  "memory": {
    "percent": 61.5,
    "used_bytes": 20615843020,
    "total_bytes": 33554432000
  },
  "gpu": {
    "index": 0,
    "name": "NVIDIA GeForce RTX 4070 Ti SUPER",
    "utilization_percent": 72,
    "memory_used_mb": 8192,
    "memory_total_mb": 16384,
    "temperature_c": 62,
    "power_w": 185
  }
}
```

### WebSocket

```
WS /api/ws/dashboard
```

1~2초마다 카메라 stats + `system` 블록 push (REST와 동일 스키마).

## 5. SSH / 원격 확인

GUI 없을 때:

```bash
curl -s localhost:8080/api/health | jq
curl -s localhost:8080/api/system/metrics | jq '.cpu,.memory,.gpu'
```

`08_ssh_healthcheck_guide.md` — grab healthcheck와 API health 병행.

## 6. 구현 메모 (Phase 5)

| 패키지 | 용도 |
|--------|------|
| `psutil` | CPU, RAM |
| `pynvml` | GPU util, VRAM, temperature (NVML) |

의존성은 Phase 5에서 `pyproject.toml` 추가. NVML은 드라이버 580+ 환경에서 동작.

## 7. 관련 문서

- `02_streaming_design.md` — FPS, 포트, 스트림
- `08_ssh_healthcheck_guide.md` — 원격 검증
- `00_project_plan.md` — Phase 5 작업 목록
