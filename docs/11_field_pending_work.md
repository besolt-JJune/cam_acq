# 현장 대기 작업 (Field Pending)

SSH 원격으로는 **물리 접근·케이블 조작**이 필요한 항목을 모아 둔다.  
완료 시 체크하고 본 문서·`00_project_plan.md` Phase 표를 갱신한다.

## 1. 완료 요약

### 1.1 2ch (2026-06-29 ~ 30)

| 항목 | 결과 |
|------|------|
| Phase 1 | ✅ 2대 grab 60s PASS, time_sync skew ~21µs |
| Phase 2.2 TimeSyncManager | ✅ `grab_healthcheck` + `time_sync` 블록 |
| Phase 2.4 socket buffer | ✅ `socket_buffer_check` PASS (rmem/wmem 20MB) |
| Phase 2.6 1h soak (2대) | ✅ PASS — cam0/1 ~22.98fps, drop 0 |
| Phase 6 T5 split + YOLO soak 1h (2대) | ✅ PASS (2026-06-30) — `cam-acq-yolo-soak --duration 3600`, 300s split 정상 |
| Phase 3 pyds + person detection (2ch) | ✅ PASS (2026-06-30) — `yolo_person_test.json`: hit 90.8%, `human_detection` trigger, overlay bbox 육안 확인 |

### 1.2 3ch 운영 전환 (2026-06-30)

| 항목 | 결과 |
|------|------|
| Phase 2.1 3대 grab / 오픈 | ✅ cam0/1/2 online (`10.10.1.3`, `10.10.4.3`, `10.10.3.3`) |
| Phase 2.3 GigE recovery (yolo-live·recording) | ✅ E2E PASS — `13_gige_disconnect_recovery.md`, `gige_disconnect` split JSON |
| Phase 3.2 YOLO engine batch=3 | ✅ `yolov8m_person_b3_gpu0_fp16.engine` |
| Phase 3 YOLO live 3ch (`gpu_phase3`) | ✅ `healthcheck/yolo_live_3ch_gpu.json` — PASS, `fps_pushed_avg` ~20.04/ch |
| Phase 3 dashboard live + event recording | ✅ `yolo_live_dashboard.sh` 운영 중 |
| Phase 4.2 수동 trigger 녹화 (3ch) | ✅ `20260630_152217_cam{0,1,2}_seg0000_manual.mp4` |
| Phase 4.3 자동 trigger 녹화 (3ch) | ✅ `20260630_152223_cam{0,1,2}_seg0000.mp4` (동시 trigger) |
| Phase 6 T1/T2/T5/T6/T9/T11/T13/T14 | ✅ event·manual 녹화, split, 메타, recovery, 재생, `/api/health` PASS |
| Phase 6 T7 FIFO_DELETE | ✅ (2026-06-30) — `20260630_010304_cam0_seg00_manual.mp4` 등 오래된 파일 삭제 확인 |

### 2.3 실패 로그 (수정 전, grab_healthcheck)

```
open_error: Device.register_device_offline_callback:
  Expected callback type is function not <class 'method'>
```

원인: gxipy는 bound method(`signal.set`) 불가 → plain function 래퍼로 수정 (`recovery.py`).

---

## 2. GigE recovery 케이블 test (Phase 2.3) — ✅ 완료 (2026-06-30, 3ch)

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

## 3. 추후 — 장시간 soak · 리소스 실측

3ch live·recording·trigger 검증 완료. **아래는 한 세션에서 일괄 진행 예정.**

### 3.1 YOLO live 1h soak (3ch) — Phase 3.4 / 6.4

2ch 1h PASS (2026-06-30). 3ch는 동일 명령:

```bash
source venv.sh
nohup uv run cam-acq-yolo-soak \
  --duration 3600 \
  --no-record \
  --output ./healthcheck/yolo_soak_3ch.json \
  > ./healthcheck/yolo_soak_3ch.log 2>&1 &
echo "pid=$!"
```

**PASS 확인:** segment split(300s), `fps_live` 추이.  
장시간 시 `ring_stats` overflow 가능 → §8.2.

### 3.2 3ch RAM/VRAM 실측 (Phase 4.9.2) — §3.1과 동시

```bash
source venv.sh
NUM_CAMERAS=3 uv run cam-acq-memory-profile \
  --output ./healthcheck/memory_profile_3ch.json
```

| 측정 | 조건 | 목적 |
|------|------|------|
| **필수** | 현행 `.env` (buffer 5s, 23fps) | 3ch ring·RSS·VRAM peak — `07_storage_capacity.md` §5.1 3ch 추정 검증 (Phase 6 **T12**) |
| **선택** | buffer **2s**, fps **20** | 단축안 RAM — `07_storage_capacity.md` §5.3 시나리오 B |

### 3.3 grab-only 1h soak (3ch) — 선택

YOLO soak(§3.1)으로 대체 가능. formal JSON이 필요하면:

```bash
nohup uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 3600 \
  --output ./healthcheck/soak_1h_3cam.json \
  > ./healthcheck/soak_1h_3cam.log 2>&1 &
```

### 3.4 Phase 4.6 코덱 프로파일 (3ch 부하) — 추후

cam0 단독 H.264/H.265 비교는 완료 → **H.264** 채택.  
3ch + YOLO + NVENC 동시 조건 재측정은 §3.1 soak 이후.

```bash
source venv.sh
uv run cam-acq-codec-profile --camera-index 0 \
  --output ./healthcheck/codec_profile.json
```

---

## 4. Phase 3·4 현장 검증 (참고)

### 4.1 pyds — ✅ (2026-06-30)

`cam-acq-yolo-live` JSON에 `detection.pyds_warning` 없음. 설치: `./scripts/ensure_pyds_wheel.sh` + `uv sync`.

### 4.2 overlay·detection (2ch) — ✅

`samples/yolo_person_test.mp4`, `healthcheck/yolo_person_test.json` (~90.8% person hit).

### 4.3 GPU debayer 3ch — ✅ (2026-06-30)

`healthcheck/yolo_live_3ch_gpu.json`:

| cam | ip | fps_pushed_avg | incomplete |
|-----|-----|----------------|------------|
| 0 | 10.10.1.3 | 20.04 | 0 |
| 1 | 10.10.4.3 | 20.04 | 0 |
| 2 | 10.10.3.3 | 20.04 | 0 |

`debayer_backend: gpu_phase3`, `status: PASS`. 기준: `fps_pushed ≥ 23×0.8` (`12_debayer_3ch_strategy.md` §4.3) — **혼합 debayer(§6) 불필요**.

### 4.4 수동·자동 녹화 (3ch) — ✅ (2026-06-30)

- 수동: `152217_*_manual.mp4` (cam0/1/2)
- 자동 event: `152223_cam{0,1,2}_seg0000.mp4`
- split: `split.reason: interval` 다수 (300s), `gige_disconnect` cam0/1 각 1건

---

## 5. 추후 선택 — GPU 2ch + CPU 1ch 혼합 live debayer

**채택 안 함 (2026-06-30).** 3ch `gpu_phase3` 실측 ~20fps ≥ `23×0.8`.

| 항목 | 내용 |
|------|------|
| 목적 | YOLO live 경로에서 GPU debayer 2체인 + CPU SDK 1ch |
| 전제 | per-camera `DEBAYER_MODE`, `gst_live` 혼합 파이프라인 — **미구현** |
| 상세 | `12_debayer_3ch_strategy.md` §4·§7 |

fps가 soak 중 크게 하락할 때만 재검토.

---

## 6. 추후 — YOLO+NVENC soak 후속

### 6.1 Phase 6 T8 — FIFO_REJECT

**미구현.** T7(FIFO_DELETE)은 2026-06-30 확인 완료.

### 6.2 Ring overflow (장시간 YOLO+NVENC)

2ch `yolo_soak.json` / `yolo_soak_t7.json`: `overflow_drops_total` 7만~10만+, `ring_stats.healthy: false`.  
4K×Nch + YOLO + NVENC 동시 시 grab > encode drain. split(T5)은 정상.

3ch soak(§3.1) 시 drain/encode 튜닝·`RECORDING_BUFFER_SEC` 재실측 또는 ring PASS 기준 검토.

---

## 7. 관련 문서

- `08_ssh_healthcheck_guide.md` — CLI 옵션, 리포트 형식
- `09_network_topology.md` — 3대 NIC / IP
- `12_debayer_3ch_strategy.md` — encode debayer, 3ch GPU 실측
- `13_gige_disconnect_recovery.md` — GigE disconnect: dashboard 재연결, recording split/resume
- `00_project_plan.md` — Phase 계획
