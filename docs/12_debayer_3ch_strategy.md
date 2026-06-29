# Debayer 전략 · 3ch 확장 논의

YOLO live debayer vs 녹화 encode debayer, 3ch 확장, `MAX_FPS` 설정에 대한 논의 기록.

## 상태

| 항목 | 지금 | 추후 |
|------|------|------|
| 3ch YOLO debayer | **전 채널 `gpu_phase3`** — cam2 연결 후 실측 (`11_field_pending_work.md` §5) | — |
| GPU 2ch + CPU 1ch 혼합 live debayer | **구현 안 함** | **선택** — 3ch `gpu_phase3` 실측이 목표 fps 미달일 때만 검토 (`§4`, `11_field_pending_work.md` §7) |
| per-camera `DEBAYER_MODE` | 미구현 | 혼합 모드 채택 시에만 |
| `MAX_FPS` + SDK 연동 | 미구현 | 필요 시 (혼합 모드 또는 fps 조정 시) |

관련: `architecture.md` §3, `11_field_pending_work.md` §5·§7, `gst_encode.py`, `gst_live.py`

---

## 1. 인코딩(녹화) 경로 — debayer 필수

녹화 MP4는 **Bayer raw를 NVENC에 직접 넣지 않는다.**  
Bayer를 그대로 H.264/H.265로 압축하면 복원 시 **demosaic 없이 모자이크(픽셀 깨짐)** 상태가 된다.  
따라서 encode 전에 **반드시 debayer(RGB/NV12)** 를 거친다.

### 실제 파이프라인 (`recording/gst_encode.py`)

```
Ring buffer (Bayer 4K raw)
  → appsrc (video/x-bayer)
  → bayer2rgb          ← GPU debayer (GStreamer)
  → videoconvert
  → cudaupload
  → nvcudah264enc | nvcudah265enc
  → qtmux → .mp4
```

- 코드: `encode_bayer_frames_to_mp4()` — docstring *"Bayer → debayer → CUDA upload → NVENC"*
- `.env` `BAYER_FORMAT` (RGGB|GRBG|…) → `bayer2rgb` caps
- `DEBAYER_MODE`와 **무관** — 녹화는 항상 위 GPU 경로 (`gpu_phase4` 개념)
- `nvv4l2*h*enc` + Bayer 4K는 segfault 이력 → `nvcuda*h*enc` 사용

### YOLO live vs 녹화 — debayer가 두 갈래

| 경로 | 시점 | debayer 위치 | 설정 |
|------|------|--------------|------|
| **YOLO live** (Phase 3) | 실시간 detection | `cpu_sdk` (SDK) 또는 `gpu_phase3` (bayer2rgb→scale→nvvideoconvert) | `.env` `DEBAYER_MODE` |
| **녹화 encode** (Phase 4) | trigger 후 ring flush | `gst_encode.bayer2rgb` + NVENC | 항상 GPU, `BAYER_FORMAT` |

live에서 cam2만 `cpu_sdk`를 써도 **녹화 MP4 품질/경로는 동일 GPU debayer**이다.

---

## 2. 전제 (운영 카메라)

| 항목 | 내용 |
|------|------|
| 해상도 | **3대 모두 4K** (4024×3036, 저해상도 미사용) |
| 구성 | 동일 사양 2대 + 센서 동일·조합(렌즈 등) 다른 1대 |
| 이질 debayer | 3번째 카메라만 debayer 알고리즘이 달라도 **화면상 이질감 없음** (시야/조합이 다름) |
| 3ch 처리량 | 우선 **전 채널 `gpu_phase3` 실측**; 미달 시에만 GPU 2ch + CPU 1ch **선택 검토** (§4) |

---

## 3. 2ch 실측 요약 (2026-06-29)

YOLO only (`cam-acq-yolo-live --no-record`), 4024×3036 → 1006×760.

| 모드 | ch 수 | fps_pushed (min) | CPU avg | PASS |
|------|-------|------------------|---------|------|
| cpu_sdk | 2 | 17.9 | 7.9% | FAIL |
| gpu_phase3 | 2 | 21.7 | 3.4% | PASS |
| cpu_sdk | 1 | 20.8 | — | PASS |
| gpu_phase3 | 1 | 22.4 | — | PASS |

해석:

- CPU %가 낮아도 `cpu_sdk`는 **프레임당 SDK demosaic 지연**으로 fps가 막힌다 (코어 포화 아님).
- 1ch `cpu_sdk`는 23fps에 근접; 2ch부터 병목.
- `gpu_phase3`가 처리량·CPU 여유 모두 유리.

2ch 리소스 (memory-profile, 녹화 포함): RAM ring ~8GB, NVENC ~28% (H.264).

---

## 4. 추후 선택 — GPU 2ch + CPU 1ch (혼합 live debayer)

> **지금 진행하지 않음.** 3ch 전부 `gpu_phase3` 실측 후 fps·리소스가 목표에 못 미칠 때만 채택 여부를 결정한다.  
> 채택 시에만 §7 구현 갭을 작업한다.

### 4.1 개요 (가설)

```
cam0,1: DEBAYER_MODE=gpu_phase3  →  GStreamer bayer2rgb 체인
cam2:   DEBAYER_MODE=cpu_sdk       →  SDK convert("RGB") + resize → appsrc RGB
녹화:   3ch 모두 ring Bayer → gst_encode.bayer2rgb (동일)
```

| 장점 | 리스크 / 제약 |
|------|----------------|
| GPU debayer 체인 2개로 YOLO 부하 완화 | **현재 코드 미지원** — 전역 `DEBAYER_MODE`, 파이프라인 전체 bayer 또는 전체 RGB |
| cam2 다른 조합 → SDK demosaic이 맞을 수 있음 | 배치 push 시 **가장 느린 채널이 전체 fps** (예상 ~20–21) |
| 녹화 품질은 live debayer와 분리 | NVENC 3ch·RAM ~12GB는 **분산으로 해결 안 됨** |
| | cam2 `BAYER_FORMAT` / `PIXEL_FORMAT` **per-camera** 필요할 수 있음 |

### 4.2 `.env` 확장 (미구현 — 혼합 모드 채택 시에만)

```env
MAX_FPS=20                    # NOMINAL_FPS 대체 — SDK AcquisitionFrameRate·ring·healthcheck 연동
DEBAYER_MODE=gpu_phase3       # 기본값

CAMERA0_DEBAYER_MODE=gpu_phase3
CAMERA1_DEBAYER_MODE=gpu_phase3
CAMERA2_DEBAYER_MODE=cpu_sdk  # 실측 후 확정
# CAMERA2_BAYER_FORMAT=...    # 패턴 다를 때만
```

`MAX_FPS=23` 고정 시 GPU2+CPU1도 구조적으로 빠듯할 수 있음 → soak 후 조정.

### 4.3 채택 결정 기준 (3ch `gpu_phase3` 실측 후)

| 측정 | 결과 | 다음 |
|------|------|------|
| `fps_pushed` 3ch ≥ `MAX_FPS×0.8` | PASS | **혼합 모드 불필요** — `gpu_phase3` 유지 |
| fps 미달, GPU debayer 병목 의심 | FAIL | §4 혼합 모드 **검토** (구현은 별도 작업) |
| NVENC % + RAM peak (녹화 동시) | 한계 | debayer 분산으로 **해결 안 됨** — 코덱·bitrate·`MAX_FPS` 등 별도 |

---

## 5. 3ch 테스트 절차

**전제:** `CAMERA2_IP` 연결·NIC (`09_network_topology.md`), `.env` `NUM_CAMERAS=3`.

### 5.1 Grab (Phase 2)

```bash
source venv.sh
uv run python -m cam_acq.tools.grab_healthcheck \
  --duration 60 --output ./healthcheck/report_3cam.json
```

통과: 3채널 `fps_avg ≥ 22`, `frame_drops=0`.

### 5.2 YOLO engine (batch=3)

```bash
uv run cam-acq-build-yolo --env-file .env --variant person --batch-size 3
# → models/yolov8m_person_b3_gpu0_fp16.engine
```

### 5.3 YOLO live — 전부 gpu_phase3

```bash
DEBAYER_MODE=gpu_phase3 uv run cam-acq-yolo-live \
  --duration 60 --no-record --no-event-recording \
  --output ./healthcheck/yolo_live_3ch_gpu.json
```

### 5.4 추후 선택 — GPU2+CPU1 (**§4 채택·구현 후에만**)

지금은 실행하지 않음. 혼합 모드 코드가 들어간 뒤:

```bash
# 구현 후 예시
CAMERA0_DEBAYER_MODE=gpu_phase3 \
CAMERA1_DEBAYER_MODE=gpu_phase3 \
CAMERA2_DEBAYER_MODE=cpu_sdk \
uv run cam-acq-yolo-live --duration 60 --no-record \
  --output ./healthcheck/yolo_live_3ch_mixed.json
```

### 5.5 리소스 (녹화 동시) — **3ch 메모리 실측 추후**

2ch 실측 완료 (`07_storage_capacity.md` §5.1). **3ch는 cam2 연결 후** 아래 실행 → `11_field_pending_work.md` §6.9.2.

```bash
NUM_CAMERAS=3 uv run cam-acq-memory-profile \
  --output ./healthcheck/memory_profile_3ch.json
```

| 항목 | 내용 |
|------|------|
| 필수 | 현행 buffer 5s / 23fps — 3ch ring·RSS·VRAM peak |
| 선택 | buffer 2s / fps 20 — 단축안 (`07_storage_capacity.md` §5.3 B) |
| 미완 | 3ch + YOLO live + trigger 녹화 동시 soak |

YOLO+trigger 녹화 integration은 사람 walk-through 또는 record-test 3ch 확장 후.

### 5.6 debayer 모드 비교 (2ch 기준 스크립트)

```bash
uv run python scripts/debayer_mode_compare.py 30
# → healthcheck/debayer_mode_compare.json
```

---

## 6. 시도 로그

### 2026-06-29 — 3ch grab (cam2 미연결)

```bash
NUM_CAMERAS=3 uv run python -m cam_acq.tools.grab_healthcheck --duration 30 \
  --output ./healthcheck/report_3cam_grab.json
```

| cam | ip | 결과 |
|-----|-----|------|
| 0 | 10.10.1.3 | PASS ~22.4 fps |
| 1 | 10.10.4.3 | PASS ~22.2 fps |
| 2 | 10.10.2.3 | **FAIL** — `Can't open device by IP` |

→ **3ch YOLO/debayer 실측은 cam2 연결 후 재시도.**

---

## 7. 구현 갭 (§4 혼합 모드 **채택 시에만**)

1. `config.py` — per-camera `debayer_mode`, optional `bayer_format`, `MAX_FPS`
2. `gst_live.py` — 스트림별 bayer 체인 vs RGB 체인
3. `deepstream_yolo_live.py` — 채널별 grab + 혼합 batch push
4. `open_camera` — `AcquisitionFrameRate` = `MAX_FPS`
5. `architecture.md` — YOLO/recording debayer 이중 경로 반영 (§3.2 갱신됨)

---

## 8. 관련 문서

| 문서 | 내용 |
|------|------|
| `architecture.md` | 시스템 흐름, encode debayer |
| `11_field_pending_work.md` §5 | 3ch 현장 체크리스트 |
| `01_sdk_feasibility.md` | SDK demosaic |
| `06_yolo_build_porting_guide.md` | batch=N engine |
