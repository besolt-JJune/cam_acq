# 현장 대기 작업 (Field Pending)

SSH 원격으로는 **물리 접근·케이블 조작**이 필요한 항목을 모아 둔다.  
완료 시 체크하고 본 문서·`00_project_plan.md` Phase 표를 갱신한다.

## 1. 원격 완료 (2026-06-29)

| 항목 | 결과 |
|------|------|
| Phase 1 | ✅ 2대 grab 60s PASS, time_sync skew ~21µs |
| Phase 2.2 TimeSyncManager | ✅ `grab_healthcheck` + `time_sync` 블록 |
| Phase 2.4 socket buffer | ✅ `socket_buffer_check` PASS (rmem/wmem 20MB) |
| Phase 2.6 1h soak (2대) | ✅ PASS — cam0/1 ~22.98fps, drop 0 |
| Phase 6 T5 split + YOLO soak 1h (2대) | ✅ PASS (2026-06-30) — `cam-acq-yolo-soak --duration 3600`, 300s split 정상 |
| Phase 3 pyds + person detection (2ch) | ✅ PASS (2026-06-30) — `yolo_person_test.json`: hit 90.8%, `human_detection` trigger, overlay bbox 육안 확인 |
| Phase 6 T7 FIFO_DELETE | 📋 추후 §8 — mergerfs 3.6T에서 임계 미달, 삭제 미발생 |
| Phase 2.3 GigE recovery (yolo-live·recording) | ✅ E2E PASS (2026-06-30, 3ch) — `11_field_pending_work.md` §2.3 |

### 2.3 실패 로그 (수정 전, grab_healthcheck)

```
open_error: Device.register_device_offline_callback:
  Expected callback type is function not <class 'method'>
```

원인: gxipy는 bound method(`signal.set`) 불가 → plain function 래퍼로 수정 (`recovery.py`).

---

## 2. 현장 전용 — 대기

### 2.1 ~~3대 camera grab~~ → 추후 (§5)

2대 test env 기준으로 Phase 2·3 진행. 3대 grab은 **§5**로 이관.

---

### 2.3 GigE recovery 케이블 test (Phase 2.3) — ✅ 완료 (2026-06-30, 3ch)

**스펙:** `13_gige_disconnect_recovery.md` §3.4·§4.6  
**실행:** `./scripts/yolo_live_dashboard.sh` — cam0 Ethernet 5~10s 분리·재연결 (event 녹화 활성 구간 포함)

| Test | 결과 |
|------|------|
| A Live | `offline` → `online`, `recovery_events`/`reconnect_success` ≥1, `fps_live` ≥22, health PASS |
| B Recording | `20260630_150442_cam0_seg0000.json` → `split.reason: gige_disconnect`; reconnect 후 `150552_cam0_seg0001` 별도 MP4 |
| C 부수 영향 | cam0만 `recovery_events:1`; cam1/cam2 `recovery_events:0` (이번 세션) |

**참고:** idle 구간 disconnect는 live recovery만 (`recovery_events`↑); 열린 NVENC seg 없으면 `gige_disconnect` JSON 없음.

```bash
# grab 전용 smoke (회귀)
uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 120 \
  --recovery \
  --output ./healthcheck/report_recovery.json
```

---

### 2.6 1시간 soak (Phase 2.6) — ✅ 완료 (2026-06-29, 2대)

| 카메라 | fps_avg | frames | drops |
|--------|---------|--------|-------|
| cam0 | 22.978 | 82728 | 0 |
| cam1 | 22.976 | 82718 | 0 |

**2대 test env PASS.** 3대 전환 후 동일 명령 재실행 필요.

<details>
<summary>실행 명령 (참고)</summary>

```bash
cd ~/works/cam_acq
export LD_LIBRARY_PATH=$PWD/sdk/Galaxy_camera/c/lib/x86_64:$LD_LIBRARY_PATH

nohup uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 3600 \
  --output ./healthcheck/soak_1h.json \
  --save-sample ./samples \
  > ./healthcheck/soak_1h.log 2>&1 &

echo "pid=$!"
tail -f ./healthcheck/soak_1h.log
# Ctrl+C 후
jq '.status'
jq '.cameras[] | {camera_index, fps_avg, frame_drops, incomplete_frames}' \
  ./healthcheck/soak_1h.json
echo exit=$?
```

</details>

---

## 5. 추후 — NUM_CAMERAS=3 (cam2 연결 후 실측)

3번째 카메라·NIC 연결 후 일괄 전환. YOLO live는 **전 채널 `gpu_phase3` 실측** (`12_debayer_3ch_strategy.md` §5).  
GPU 2ch + CPU 1ch 혼합 debayer는 **추후 선택** — §7.

### 5.0 선행 조건

- `CAMERA2_IP` / `CAMERA2_INTERFACE` 연결 확인
- cam2 grab PASS 후 YOLO·debayer 비교 진행

### 5.1 3대 camera grab (Phase 2.1)

**전제:** 3번째 카메라 + NIC 포트 (`docs/09_network_topology.md`)

```bash
# .env
NUM_CAMERAS=3
CAMERA2_IP=10.10.2.x
# CAMERA2_INTERFACE=enp23s0

uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 60 --save-sample ./samples \
  --output ./healthcheck/report_3cam.json
```

**통과:** 3채널 `fps_avg ≥ 22`, `frame_drops=0`

**2026-06-29 시도:** cam0/1 PASS, cam2 (`10.10.2.3`) open 실패 — `healthcheck/report_3cam_grab.json`

### 5.2 YOLO / DeepStream 3ch

```bash
uv run cam-acq-build-yolo --env-file .env --variant person --batch-size 3
# → models/yolov8m_person_b3_gpu0_fp16.engine
# nvinfer batch-size=3, deepstream num-sources=3 (config 별도 추가)
```

```bash
# 전부 gpu_phase3 (결정 전 baseline)
DEBAYER_MODE=gpu_phase3 uv run cam-acq-yolo-live \
  --duration 60 --no-record --no-event-recording \
  --output ./healthcheck/yolo_live_3ch_gpu.json
```

통과 기준·인코딩 debayer: `12_debayer_3ch_strategy.md` §5. 혼합 debayer(§7)는 **3ch gpu_phase3 실측 FAIL 시에만** 검토.

### 5.3 1시간 soak (3대)

`NUM_CAMERAS=3` 설정 후 §2.6과 동일 명령 재실행.

---

## 6. Phase 3 현장 검증

**2ch (2026-06-30):** pyds·overlay·trigger 검증 완료. **남음:** §6.7 YOLO 자동 trigger → NVENC 녹화 E2E.

### 6.1 pyds 설치 (nvinfer probe) — ✅ 완료 (2026-06-30)

DS 9는 pyds wheel 미동봉. `uv sync` 후에도 유지되도록 pyproject에 포함:

```bash
cd ~/works/cam_acq
./scripts/ensure_pyds_wheel.sh   # DS wheel → vendor/pyds-*.whl 심링크
uv sync
python3 -c "from cam_acq.detection.pyds_loader import import_pyds; import_pyds(); print('pyds OK')"
```

`setup_deepstream_yolo.sh` 마지막에 `ensure_pyds_wheel.sh` 호출됨.

wheel이 없을 때만 빌드 (`pip3 install build` 선행):

```bash
cd /opt/nvidia/deepstream/deepstream/sources/deepstream_python_apps/bindings
export CMAKE_BUILD_PARALLEL_LEVEL=$(nproc)
python3 -m build
./scripts/ensure_pyds_wheel.sh && uv sync
```

**PASS:** `cam-acq-yolo-live` JSON에 `detection.pyds_warning` 없음.

### 6.2 overlay·detection 육안 검증 (3.4) — ✅ 완료 (2026-06-30)

- `samples/yolo_person_test.mp4` — person bbox, 화면 정상(대각선 밀림 없음) 육안 확인
- `healthcheck/yolo_person_test.json` — `person_frame_hits` 3518 / `frames_with_meta` 3876 (~90.8%)
- `DETECTION_CONFIDENCE=0.5` 유지 (추가 튜닝 불필요)

진단용 취득 명령:

```bash
source venv.sh
uv run cam-acq-yolo-live \
  --duration 90 \
  --record samples/yolo_person_test.mp4 \
  --no-event-recording \
  --output healthcheck/yolo_person_test.json
```

### 6.3 trigger 이벤트 (3.5) — ✅ 완료 (2026-06-30)

사람 walk-through 시 `detection.trigger_events` 에 `human_detection` 기록 확인 (`yolo_person_test.json`).

```bash
jq '.detection' healthcheck/yolo_person_test.json
```

Phase 4 자동 녹화 E2E는 §6.7.

### 6.4 YOLO live soak (안정성) — ✅ 1h PASS (2026-06-30, 2대)

`cam-acq-yolo-soak` 3600s, `RECORDING_SPLIT_INTERVAL_SEC=300` — cam0/1 segment 분할 정상 (Phase 6 **T5**).

```bash
source venv.sh
nohup uv run cam-acq-yolo-soak \
  --duration 3600 \
  --no-record \
  --output ./healthcheck/yolo_soak.json \
  > ./healthcheck/yolo_soak.log 2>&1 &
echo "pid=$!"
```

**PASS 확인:** `jq '.recording.segment_count, .recording.max_segment_index' ./healthcheck/yolo_soak.json`  
split 파일: `STORAGE_PATH` 아래 `*_seg0000_*`, `*_seg0001_*`, … (300초 간격 타임스탬프).  
장시간 soak 시 JSON `status`는 `ring_stats` overflow로 FAIL일 수 있음 → §8.

#### 6.4.1 Phase 6 T7 — FIFO_DELETE

→ **§8** (추후). 90분 soak (`yolo_soak_t7.json`)에서도 split 정상, FIFO 미동작 확인.

### 6.5 GPU debayer — Phase 3 (`gpu_phase3`) — ✅ 2ch 실측 (2026-06-30)

`.env` `DEBAYER_MODE=gpu_phase3` — YOLO live 경로: `bayer2rgb` → `videoscale` → `nvvideoconvert` (CPU SDK debayer 대체).  
`yolo_person_test.json` 에서 `debayer_backend: gpu_phase3`, 2ch ~21.75fps PASS.

Bayer 패턴: `.env` `BAYER_FORMAT` (RGGB|GRBG|GBRG|BGGR). 카메라 보고값은 `cam-acq-bayer-pattern-check`로 확인.

```bash
source venv.sh
uv run cam-acq-bayer-pattern-check --camera-index 0 --output-dir ./healthcheck/bayer_pattern
# cam0.raw + cam0_{RGGB,GRBG,GBRG,BGGR}.bmp — 색이 자연스러운 패턴을 BAYER_FORMAT에 설정
```

녹화 encode debayer: `gpu_phase4` = `gst_encode.bayer2rgb` (이미 적용).

### 6.6 Phase 4 수동 trigger 녹화 (4.2~4.8)

카메라 2대 + `STORAGE_PATH` 마운트 후:

```bash
source venv.sh
# manual: trigger-at 에 start, 이후 buffer_sec 이상 녹화 후 자동 stop (record_test 내장)
uv run cam-acq-record-test --duration 28 --trigger-at 8 --output ./healthcheck/record_test.json
```

출력 파일: `*_manual.mp4` (basename `_manual` 접미사).

PASS 조건: JSON `status`=`PASS`, `segments[]`에 cam0/cam1 MP4·`.json`·`.frames.jsonl` 경로, `ring_memory_bytes` 기록.

GPU encode 단독 smoke (`GST_ENCODE_TEST=1`):

```bash
GST_ENCODE_TEST=1 uv run python tests/test_recording.py
```

**참고:** `nvv4l2h264enc`+Bayer 4K 경로는 segfault — `gst_encode.py`는 `nvcudah264enc`/`nvcudah265enc` 사용.

### 6.7 Phase 4.3 YOLO live + 자동 trigger 녹화 — **추후 (사람 walk-through)**

**코드:** `cam-acq-yolo-live`가 person trigger 시 Bayer ring → NVENC (`--no-event-recording`으로 비활성).

**현장 검증 보류:** 사람이 오가는 walk-through 테스트 불가. 아래는 환경이 되면 수행.

```bash
source venv.sh
uv run cam-acq-yolo-live --duration 120 --no-record --output ./healthcheck/yolo_live_record.json
jq '.recording.segments, .detection.trigger_events' ./healthcheck/yolo_live_record.json
```

PASS (추후): `detection.trigger_events`에 `human_detection` + `recording.segments[]`에 MP4·메타 경로.

지금 가능한 대체: §6.6 `cam-acq-record-test` (수동 trigger), 단위 테스트 `tests/test_detection.py`.

### 6.8 Phase 4.6 코덱 프로파일 (cam0)

cam1 촬영 위치 부적합 → **cam0 단독**으로 동일 Bayer 윈도우를 H.264/H.265 각각 NVENC.

```bash
source venv.sh
# buffer 5s, split 360s → duration 370s, trigger-at 5s (defaults from .env)
uv run cam-acq-codec-profile --camera-index 0 \
  --output ./healthcheck/codec_profile.json
```

리포트: `encodes[]` — `file_bytes`, `encode_sec`, `effective_mbps`, `gpu_peak_util_pct`, `encoder_peak_util_pct`, `h265_vs_h264_size_ratio`.

결과 반영: `.env` `ENCODING_CODEC`, `docs/07_storage_capacity.md` 표 갱신.

### 6.9 Phase 4.9 RAM/VRAM 실측

#### 6.9.1 2ch — 완료 (2026-06-29)

```bash
source venv.sh
uv run cam-acq-memory-profile --output ./healthcheck/memory_profile.json
```

기본: `RECORDING_BUFFER_SEC=5`, 23fps, duration 40s (ring fill + trigger/encode), 1s poll.  
리포트: `ring_memory_bytes_total`, `peaks.*`. 상세: `07_storage_capacity.md` §5.1.

#### 6.9.2 3ch — **추후** (cam2 연결 후)

**전제:** `NUM_CAMERAS=3`, 3ch grab PASS (`§5.1`), YOLO engine `batch=3` (`§5.2`).

```bash
source venv.sh
NUM_CAMERAS=3 uv run cam-acq-memory-profile \
  --output ./healthcheck/memory_profile_3ch.json
```

| 측정 | 조건 | 목적 |
|------|------|------|
| **필수** | 현행 `.env` (buffer 5s, 23fps) | 3ch ring·RSS·VRAM peak — `07_storage_capacity.md` §5.1 3ch 추정 검증 |
| **선택** | buffer **2s**, fps **20** (`.env`/`AcquisitionFrameRate` 변경 후) | 단축안 RAM — `07_storage_capacity.md` §5.3 시나리오 B |

3ch+YOLO 동시 부하는 `cam-acq-yolo-live` / record-test integration 후 추가 soak 권장.  
절차: `12_debayer_3ch_strategy.md` §5.5.

---

## 7. 추후 선택 — GPU 2ch + CPU 1ch 혼합 live debayer

**지금 진행하지 않음.** 3ch 전부 `gpu_phase3` 실측(§5)이 목표 fps에 **미달**할 때만 채택 여부를 결정한다.

| 항목 | 내용 |
|------|------|
| 목적 | YOLO live 경로에서 GPU debayer 2체인 + CPU SDK 1ch (cam2 다른 조합 4K) |
| 전제 | per-camera `DEBAYER_MODE`, `gst_live` 혼합 파이프라인 — **미구현** |
| 녹화 | 영향 없음 — encode는 항상 `gst_encode.bayer2rgb` (GPU) |
| 상세 | `12_debayer_3ch_strategy.md` §4·§7 |

채택 시: `12_debayer_3ch_strategy.md` §5.4 혼합 `cam-acq-yolo-live` 검증 추가.

---

## 8. 추후 — YOLO+NVENC soak 후속 (2026-06-30 보류)

다른 작업 우선. 아래는 재개 시 참고.

### 8.1 Phase 6 T7 — FIFO_DELETE

**시도:** `yolo_soak_t7.json` (5403s, seg0~17). **삭제 없음** — `maybe_fifo_cleanup()` 미호출.

**원인:** `usage_ratio()`는 **mergerfs 마운트 전체** (`/mnt/data_pool`) 기준. 3.6TB에서 사용 ~0.46% (18GB) → `STORAGE_FULL_PERCENTAGE=1` (≈36GB 필요) 미달.

**재검증 옵션:**

| 방법 | 내용 |
|------|------|
| 테스트용 `STORAGE_FULL_PERCENTAGE=0` | 임계 항상 충족 → segment open 시 삭제 관찰 |
| 운영식 `95` + 더미 채우기 | 마운트 95% 근처까지 채운 뒤 soak |
| 코드 개선 (선택) | recordings 디렉터리 용량 기준 FIFO, JSON에 `fifo_removed` 카운트 |

**T8** `FIFO_REJECT` — 미구현.

### 8.2 Ring overflow (장시간 YOLO+NVENC)

`yolo_soak.json` / `yolo_soak_t7.json`: `overflow_drops_total` 7만~10만+, `ring_stats.healthy: false`.  
4K×2ch + YOLO + NVENC 동시 시 grab > encode drain. split(T5)은 정상.

재개 시: drain/encode 튜닝, `RECORDING_BUFFER_SEC`·해상도·fps 재실측, 또는 ring 리포트 기준 PASS 정의 검토.

---

## 4. 관련 문서

- `08_ssh_healthcheck_guide.md` — CLI 옵션, 리포트 형식
- `09_network_topology.md` — 3대 NIC / IP
- `12_debayer_3ch_strategy.md` — encode debayer, 3ch GPU/CPU 논의·실측 절차
- `13_gige_disconnect_recovery.md` — GigE disconnect: dashboard 재연결, recording split/resume
- `00_project_plan.md` — Phase 계획
