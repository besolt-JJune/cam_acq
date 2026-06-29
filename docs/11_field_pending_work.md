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

## 5. 추후 — NUM_CAMERAS=3 (지금 진행하지 않음)

3번째 카메라·NIC 연결 후 일괄 전환. 2대 환경에서는 아래를 **실행하지 않는다**.

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

### 5.2 YOLO / DeepStream 3ch

```bash
uv run cam-acq-build-yolo --env-file .env --variant person --batch-size 3
# → models/yolov8m_person_b3_gpu0_fp16.engine
# nvinfer batch-size=3, deepstream num-sources=3 (config 별도 추가)
```

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

### 6.3 trigger 이벤트 (3.5)

사람 walk-through 시 JSON `detection.trigger_events` 에 `human_detection` 기록.

```bash
uv run cam-acq-yolo-live --duration 60 --output ./healthcheck/yolo_live_trigger.json
jq '.detection' ./healthcheck/yolo_live_trigger.json
```

### 6.4 YOLO live soak (안정성)

30분~1시간 `cam-acq-yolo-live` — FPS·메모리·MP4 반복 확인 (사람 없어도 가능, trigger 검증은 §6.3).

### 6.5 GPU debayer — Phase 3 경로 (3.6)

`.env` `DEBAYER_MODE=gpu_phase3` — **미구현** (인터페이스만). 녹화용 GPU debayer는 Phase 4 (`gpu_phase4`).

---

## 4. 관련 문서

- `08_ssh_healthcheck_guide.md` — CLI 옵션, 리포트 형식
- `09_network_topology.md` — 3대 NIC / IP
- `00_project_plan.md` — Phase 계획
