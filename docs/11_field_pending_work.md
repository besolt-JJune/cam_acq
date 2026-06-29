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
| Phase 2.3 `--recovery` (코드) | ⚠️ callback 버그 수정됨 — **현장 재검증 필요** |

### 2.3 실패 로그 (수정 전)

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

### 2.3 GigE recovery 케이블 test (Phase 2.3)

**전제:** `--recovery` 코드 pull 후, grab 중 **1회** Ethernet 분리·재연결

```bash
uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 120 \
  --recovery \
  --output ./healthcheck/report_recovery.json

# soak 중 cam0 또는 cam1 케이블 5~10초 분리 → 재연결
jq '.cameras[].recovery' ./healthcheck/report_recovery.json
```

**기대:**

- `offline_events ≥ 1`
- `reconnect_success ≥ 1`
- soak 종료 후 `status: PASS` (FPS 기준 유지)

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

## 6. 추후 — Phase 3 현장 검증 (코드 완료, 테스트 대기)

코드는 반영됨. 아래는 **사람·카메라·pyds** 가 필요한 검증만 남음.

### 6.1 pyds 설치 (nvinfer probe)

DS 9는 pyds wheel 미동봉. bindings 빌드 후 venv에 설치:

```bash
# /opt/nvidia/deepstream/deepstream/sources/ 에 deepstream_python_apps clone
cd deepstream_python_apps/bindings
export CMAKE_BUILD_PARALLEL_LEVEL=$(nproc)
python3 -m build
uv pip install dist/pyds-*.whl
```

`cam-acq-yolo-live` JSON의 `detection.pyds_warning` 이 없어야 probe 동작.

### 6.2 overlay·detection 육안 검증 (3.4)

- `samples/deepstream_yolo_overlay_live_2ch.mp4` — person bbox만, 화면 정상(대각선 밀림 없음)
- `DETECTION_CONFIDENCE` 튜닝

### 6.3 trigger 이벤트 (3.5) — **추후 (사람 walk-through)**

촬영 환경상 사람이 오가는 테스트가 불가하면 **보류**. 가능해질 때 아래로 검증.

사람 walk-through 시 JSON `detection.trigger_events` 에 `human_detection` 기록.

```bash
source venv.sh
uv run cam-acq-yolo-live --duration 60 --output ./healthcheck/yolo_live_trigger.json
jq '.detection' ./healthcheck/yolo_live_trigger.json
```

Phase 4 자동 녹화 E2E는 §6.7.

### 6.4 YOLO live soak (안정성)

30분~1시간 `cam-acq-yolo-live` — FPS·메모리·MP4 반복 확인 (사람 없어도 가능, trigger 검증은 §6.3).

### 6.5 GPU debayer — Phase 3 (`gpu_phase3`)

`.env` `DEBAYER_MODE=gpu_phase3` — YOLO live 경로: `bayer2rgb` → `videoscale` → `nvvideoconvert` (CPU SDK debayer 대체).

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
# duration >= trigger_at + 2×RECORDING_BUFFER_SEC (예: buffer 5s, trigger 8s → duration 28)
uv run cam-acq-record-test --duration 28 --trigger-at 8 --output ./healthcheck/record_test.json
```

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

### 6.9 Phase 4.9 RAM/VRAM 실측 (2ch)

```bash
source venv.sh
uv run cam-acq-memory-profile --output ./healthcheck/memory_profile.json
```

기본: duration 40s (ring fill 20s + trigger/encode), 1s poll. 리포트 `ring_memory_bytes_total`, `peaks.*`.

3ch·YOLO 동시는 integration test 때 재측정.

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

## 4. 관련 문서

- `08_ssh_healthcheck_guide.md` — CLI 옵션, 리포트 형식
- `09_network_topology.md` — 3대 NIC / IP
- `12_debayer_3ch_strategy.md` — encode debayer, 3ch GPU/CPU 논의·실측 절차
- `00_project_plan.md` — Phase 계획
