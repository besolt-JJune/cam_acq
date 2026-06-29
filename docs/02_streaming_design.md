# Streaming 설계

## 1. 원칙

| 원칙 | 설명 |
|------|------|
| 4K 미전송 | Web UI에는 **resize 해상도**만 전송 |
| 수신 FPS 유지 | Collector는 카메라 취득 FPS(23fps)로 데이터 수집 |
| 표시 FPS 분리 | `UI_MAX_DISPLAY_FPS`로 브라우저 렌더 상한만 제한 |
| 로컬 전용 | 폐쇄망, 유지보수 시에만 외부 접근 |
| 리소스 최소화 | 인코딩된 4K live stream 없음 |

## 2. FPS 개념

| 용어 | 의미 | 값 |
|------|------|-----|
| **수신 FPS** | Data Collector가 파이프라인에서 받는 FPS | 카메라 23fps |
| **UI_MAX_DISPLAY_FPS** | Dashboard가 화면에 그리는 상한 | 기본 15 (`.env`) |

수집은 23fps로 하되, UI가 15fps만 그려도 **메타데이터·FPS 통계는 23fps 기준**이다.  
브라우저 부하가 문제일 때만 `UI_MAX_DISPLAY_FPS`를 낮춘다.

## 3. 아키텍처

```
[DeepStream Preprocess]
    resize frame (960×540) ──► Data Collector (23fps)
                                    │
                    detection meta ──┤
                    FPS/storage ─────┤
                    CPU/RAM/GPU/temp ┤
                                    ▼
                          WebSocket / MJPEG
                                    ▼
              Dashboard: 시스템 패널 + 카메라 (≤ UI_MAX_DISPLAY_FPS)
```

### 스트리밍 주체

| 역할 | 모듈 |
|------|------|
| 프레임 소스 | Camera Grab |
| Resize | DeepStream preprocess (detection과 공유) |
| UI 전송 | Monitoring (Python FastAPI) |
| 녹화 스트림 | Recording (별도, trigger 시 full-res encode) |

녹화 경로는 Streaming과 **분리**된다. 녹화는 Bayer → debayer → NVENC.

## 4. 채널

| 항목 | 값 |
|------|-----|
| NIC | 4ch |
| Dashboard 최대 | 4채널 |
| 현재 (2대) | `NUM_CAMERAS=2` |
| 추후 (운영) | `NUM_CAMERAS=3` — `11_field_pending_work.md` §5 |

## 5. 대역폭 추정 (로컬)

```
4ch × 23fps × JPEG ~50KB (960×540) ≈ 4~5 MB/s
```

localhost/WebSocket으로 충분하다.

## 6. `.env`

```bash
MONITORING_WEB_PORT=8080
UI_MAX_DISPLAY_FPS=15
SYSTEM_METRICS_POLL_SEC=2
CPU_WARN_PERCENT=85
RAM_WARN_PERCENT=85
GPU_UTIL_WARN_PERCENT=90
GPU_TEMP_WARN_C=80
GPU_TEMP_CRITICAL_C=90
RESIZE_WIDTH=960
RESIZE_HEIGHT=540
```

## 7. Phase 5 API (구현)

```
GET  /api/health
GET  /api/system/metrics          # CPU (+ temperature_c), RAM, GPU util, VRAM, temperature
GET  /api/cameras/{camera_index}/stats
GET  /api/cameras/{camera_index}/params
PATCH /api/cameras/{camera_index}/params
GET  /api/stream/{camera_index}   # MJPEG multipart
GET  /api/snapshot/{camera_index} # single JPEG
WS   /api/ws/dashboard            # 메트릭·상태 push
POST /api/recording/trigger       # 수동 녹화 시작
POST /api/recording/stop          # 수동 녹화 종료
```

SSH만 가능한 경우:

```bash
curl -s localhost:8080/api/health | jq
curl -s localhost:8080/api/system/metrics | jq '.cpu,.memory,.gpu'
```

Dashboard UI·레이아웃·임계치: `10_monitoring_design.md`

## 8. 관련 문서

- `10_monitoring_design.md` — 시스템 메트릭, Dashboard UI
- `08_ssh_healthcheck_guide.md` — GUI 없이 취득 확인
- `architecture.md` — 전체 파이프라인
