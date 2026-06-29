# SSH 원격 환경 — 카메라 취득 안정성 확인 가이드

## 1. 목적

개발 환경이 **SSH 원격**이고 현장에 Viewer/GUI가 없을 때,  
개발자가 **취득 안정성을 객관적으로 확인**하기 위한 절차.

## 2. 배경

| 항목 | 내용 |
|------|------|
| Test 환경 | 카메라 **2대** |
| 운영 환경 | 카메라 **3대** |
| Viewer | 3대 연결 확인 완료, 에이징 미진행 |
| 확인 불가 | GUI 실시간 모니터링 |

## 3. 도구: `grab_healthcheck`

카메라를 N초간 취득하고 FPS·드랍·프레임 완전성을 측정해  
**JSON 리포트 + 종료 코드(PASS/FAIL)** 를 남기는 CLI.

> Phase 1 CLI (`cam_acq.tools.grab_healthcheck`)

### 3.1 실행

```bash
cd /path/to/cam_acq

uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 60 \
  --output ${HEALTHCHECK_OUTPUT_DIR:-/var/log/cam_acq/healthcheck}/report.json \
  --save-sample ./samples/ \
  --log ${LOG_PATH:-/var/log/cam_acq}
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--duration` | 60 | soak 시간(초) |
| `--output` | `.../report.json` | 결과 JSON 경로 |
| `--save-sample` | (없음) | 채널별 샘플 이미지 디렉터리 |
| `--log` | LOG_PATH | 텍스트 로그 |
| `--no-timestamp-reset` | (없음) | 세션 시작 `TimestampReset` 생략 |
| `--recovery` | (없음) | GigE offline callback + IP 재연결 |
| `--min-fps` | 22.0 | PASS 최소 평균 FPS |

### 3.2 종료 코드

| 코드 | 의미 |
|------|------|
| 0 | PASS |
| 1 | FAIL (기준 미달 또는 카메라 오픈 실패) |
| 2 | 설정/환경 오류 (.env, SDK path 등) |

## 4. `timestamp_test` (세션 timestamp 앵커)

PTP 미지원 환경에서 카메라 내부 카운터 feature 확인 및 `TimestampReset` 실행.

```bash
uv run python -m cam_acq.tools.timestamp_test --output ./healthcheck/timestamp_report.json
uv run python -m cam_acq.tools.timestamp_test --reset --output ./healthcheck/timestamp_reset.json
```

| 옵션 | 설명 |
|------|------|
| (기본) | `TimestampReset`/`TimestampLatch` implemented 여부 + latch 값 |
| `--reset` | latch → `TimestampReset` → latch (before/after JSON) |

종료 코드: `ptp_test`와 동일 (0=성공, 1=오픈/리셋 실패, 2=설정 오류).

## 5. `socket_buffer_check` (GigE 버퍼)

```bash
uv run python -m cam_acq.tools.socket_buffer_check --output ./healthcheck/socket_buffer.json
```

`/proc/sys/net/core/rmem_max`, `wmem_max`가 `SOCKET_BUFFER_MIN_BYTES`(기본 10MB) 이상이면 PASS.  
FAIL 시: `sudo sdk/Galaxy_camera/c/SetSocketBufferSize.sh 20971520`

## 6. PASS / FAIL 기준

| 항목 | FAIL 조건 |
|------|-----------|
| `fps_avg` | < `--min-fps` (기본 22.0) |
| `frame_drops` | > 0 |
| `incomplete_frames` | > 0 |
| `frames_received` | < `duration × 23 × 0.95` |
| 카메라 오픈 | 1대라도 실패 |

## 7. 리포트 형식 (`report.json`)

```json
{
  "schema_version": "1.0",
  "status": "PASS",
  "started_at": "2025-06-28T14:30:22+09:00",
  "ended_at": "2025-06-28T14:31:22+09:00",
  "duration_sec": 60,
  "num_cameras_configured": 2,
  "num_cameras_active": 2,
  "criteria": {
    "min_fps": 22.0,
    "max_frame_drops": 0,
    "max_incomplete_frames": 0
  },
  "cameras": [
    {
      "camera_index": 0,
      "ip": "192.168.1.101",
      "width": 3840,
      "height": 2160,
      "pixel_format": "BayerRG8",
      "frames_received": 1380,
      "fps_avg": 23.0,
      "fps_min": 22.3,
      "frame_drops": 0,
      "incomplete_frames": 0,
      "timestamp_monotonic": true,
      "sample_image": "samples/cam0_last.jpg"
    }
  ],
  "summary": "All cameras passed stability check."
}
```

`time_sync` 블록(Phase 2): 세션 시작 `TimestampReset` + `host_t0_wall`, 채널별 `camera_ts0`. skew가 `CROSS_CAMERA_SKEW_TOLERANCE_MS` 초과 시 `time_sync_warning` 추가.

### 샘플 이미지

`--save-sample` 사용 시 채널별 마지막 프레임 JPEG 저장.  
Bayer → SDK `convert("RGB")` 후 저장 (육안 확인용).

```bash
scp user@cam-server:/path/to/cam_acq/samples/cam0_last.jpg ./
```

## 8. 개발자 워크플로 (SSH)

### 6.1 기본 확인 (2대 test env)

```bash
ssh user@cam-server
cd /path/to/cam_acq

cat .env | grep -E 'CAMERA|NUM_CAMERAS'

uv run python -m cam_acq.tools.grab_healthcheck --duration 60

echo "exit=$?"
jq '.status'
jq '.cameras[] | {camera_index, fps_avg, frame_drops}' \
  /var/log/cam_acq/healthcheck/report.json
```

### 6.2 장시간 soak (Phase 2)

```bash
nohup uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 3600 \
  --output /var/log/cam_acq/healthcheck/soak_1h.json \
  > /var/log/cam_acq/healthcheck/soak_1h.log 2>&1 &

tail -f /var/log/cam_acq/healthcheck/soak_1h.log
jq .status /var/log/cam_acq/healthcheck/soak_1h.json
```

### 6.3 원격 회수

```bash
scp user@cam-server:/var/log/cam_acq/healthcheck/report.json ./
scp user@cam-server:/path/to/cam_acq/samples/*.jpg ./
```

## 9. 로그

| 파일 | 내용 |
|------|------|
| `healthcheck/report.json` | 구조화 결과 |
| `healthcheck/grab_YYYYMMDD.log` | 텍스트 로그 |
| `LOG_PATH/YYYY-MM-DD.log` | 시스템 통합 로그 |

## 10. Phase별 사용

| Phase | 명령 | 목적 |
|-------|------|------|
| 1 | `--duration 60` | 2대 기본 안정 확인 |
| 1 | `timestamp_test --reset` | 세션 timestamp 앵커 확인 |
| 1 | `--save-sample` | 육안 화질 확인 |
| 2 | `--duration 3600` | 1시간 soak |
| 2 | `NUM_CAMERAS=3` | **추후** — `11_field_pending_work.md` §5 |
| 5+ | `GET /api/health` | Web 카메라·시스템 요약 |
| 5+ | `GET /api/system/metrics` | CPU, RAM, GPU, 온도 |

Phase 5 이후:

```bash
uv run cam-acq-monitoring &

curl -s localhost:8080/api/health | jq
curl -s localhost:8080/api/system/metrics | jq '.cpu,.memory,.gpu,.disk_io'
curl -s localhost:8080/api/system/metrics | jq '.storage'
curl -s localhost:8080/api/health | jq '.system.storage,.cameras,.recording,.timesync,.prebuffer'
curl -s localhost:8080/api/cameras/0/stats | jq
```

원격 Dashboard: SSH `-p 2258 -L 8080:localhost:8080 user@host` 후 로컬 `http://localhost:8080`

Dashboard UI: `10_monitoring_design.md`

## 11. 트러블슈팅

| 증상 | 확인 |
|------|------|
| FAIL fps 낮음 | MTU/jumbo, `SetSocketBufferSize.sh`, 링크 속도 |
| incomplete_frames > 0 | CPU/버퍼, 패킷 손실 |
| frame_drops > 0 | grab 스레드 부하 |
| GPU 온도 critical | NVENC+YOLO 부하, `GPU_TEMP_*` 임계치, 냉각 |
| RAM warn | pre-buffer 실측 (`07_storage_capacity.md`) |
| exit=2 | `LD_LIBRARY_PATH`, gxipy, IP 오타 |
| sample 색 이상 | Bayer `PixelColorFilter` / demosaic 설정 |

## 12. 관련 문서

- `00_project_plan.md` — Phase 1
- `10_monitoring_design.md` — Dashboard, host metrics
- `11_field_pending_work.md` — 현장 대기 (3대, recovery, 1h soak)
- `01_sdk_feasibility.md` — Demosaic
- `04_install_guide.md` — Socket buffer
