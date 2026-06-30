# 3ch 리소스·코덱 실측 (Resource Profiling)

3대 운영 환경에서 **RAM/VRAM·NVENC·ring** 및 **코덱** 부하를 기록한다.  
측정마다 본 문서에 결과를 추가하고, 요약 수치는 `07_storage_capacity.md` §5와 `00_project_plan.md` Phase 4·6에 반영한다.

**관련:** `11_field_pending_work.md` §3, `12_debayer_3ch_strategy.md`, `07_storage_capacity.md`

---

## 0. 측정 상태

| ID | 항목 | 도구 | 상태 |
|----|------|------|------|
| R1 | Pre-buffer RAM/VRAM (grab + GPU encode) | `cam-acq-memory-profile` | ✅ 2026-06-30 (60s) |
| R2 | 코덱 프로파일 (3ch + YOLO 부하) | `cam-acq-codec-profile` | ⏳ 추후 |
| R3 | YOLO live 1h soak (3ch) | `cam-acq-yolo-soak` | ⏳ 추후 — `11_field_pending_work.md` §3.1 |

---

## 1. 공통 측정 조건 (운영 `.env`)

| 항목 | 값 |
|------|-----|
| `NUM_CAMERAS` | 3 |
| 카메라 IP | cam0 `10.10.1.3`, cam1 `10.10.4.3`, cam2 `10.10.3.3` |
| 해상도 | 4024×3036 (BayerRG8) |
| `RECORDING_BUFFER_SEC` | **2** (유지) |
| `DEBAYER_MODE` | `gpu_phase3` (YOLO live); 녹화 encode는 항상 `gst_encode.bayer2rgb` (GPU) |
| `ENCODING_CODEC` | H264 |
| 호스트 RAM | 32 GB |
| GPU | RTX 4070 Ti Super 16 GB |

Ring capacity (`buffer.py`): `int(23 × 2 × 3) + 5` = **143 frames/ch**.

---

## 2. R1 — Memory profile (2026-06-30)

### 2.1 실행

```bash
source venv.sh
uv run cam-acq-memory-profile \
  --duration 60 \
  --trigger-at 11 \
  --poll-sec 1 \
  --output ./healthcheck/memory_profile_3ch_60s.json
```

| 파라미터 | 값 | 비고 |
|----------|-----|------|
| `duration_sec` | 60 | |
| `trigger_at_sec` | 11 | ring soak 후 수동 trigger (`buffer×3+5`) |
| 부하 | 3ch grab + 1회 manual encode flush | **YOLO live 미포함** |

산출물: `healthcheck/memory_profile_3ch_60s.json` (gitignore)

### 2.2 타임라인

| 구간 | 대략 시각 | 내용 |
|------|-----------|------|
| soak | 0–11s | ring 채움 → **5.24 GB** 안정 |
| manual_recording | 11–13s | trigger, grab·녹화 동시 |
| encoding | ~14–15s | 3ch NVENC flush (`segments_written: 3`) |
| post_encode | 16–60s | ring 유지, grab 계속 |

### 2.3 리소스 peak

| 항목 | 값 | Phase 6 T12 (32 GB) |
|------|-----|---------------------|
| Ring (Bayer, measured) | **5.24 GB** (ch당 1.65 GB) | ✅ |
| Process RSS peak | **7.90 GB** | ✅ |
| System RAM peak | **11.9 GB** (38.5%) | ✅ |
| VRAM peak (encode 중) | **2815 MB** | ✅ (idle ~811 MB) |
| GPU encoder peak | **64%** | 3ch 동시 NVENC |
| GPU compute peak | 29% | debayer + encode |

### 2.4 채널별 grab (60s 합계)

| cam | ring_push | overflow_drops | encoder_pushed | avg push fps |
|-----|-----------|----------------|----------------|--------------|
| 0 | 1374 | 1231 | 119 | 22.9 |
| 1 | 1369 | 1226 | 119 | 22.8 |
| 2 | 1186 | 1043 | 103 | **19.8** |

cam2는 YOLO live 실측(`yolo_live_3ch_gpu.json`)과 같이 push fps가 cam0/1보다 낮다.

### 2.5 Ring health

| 항목 | 값 |
|------|-----|
| `ring_stats.healthy` | **false** |
| `overflow_drops_total` | 3500 |
| `encode_errors` | `[]` |
| JSON `status` | `FAIL` (overflow 기준; RAM 초과 아님) |

**해석**

- **soak(0–11s):** overflow 없이 ring 정상 충전 → pre-buffer **2s × 3ch** 용량 검증 OK.
- **trigger 이후:** grab(~23 fps)이 NVENC drain보다 빨라 ring full → overflow 누적. 장시간 event 녹화 시 프레임 손실 가능 (2ch YOLO soak `§8.2`와 동일 패턴).
- **25s 측정 대비:** peak RAM/VRAM 동일, overflow만 시간 비례 증가 (1192 → 3500).

### 2.6 2ch 실측·3ch 추정 대비 (`07_storage_capacity.md` §5.3 시나리오 B)

| 항목 | 3ch 추정 (20fps / 2s) | 3ch 실측 R1 |
|------|----------------------|-------------|
| Ring (Bayer) | ~4.3 GB | **5.24 GB** (23fps nominal capacity 식) |
| RSS | ~8–10 GB | **7.90 GB** (encode peak) |

`RECORDING_BUFFER_SEC=2` 유지 시 **32 GB RAM 내 3ch GPU encode 여유 확인** (T12 PASS).

---

## 3. R2 — Codec profile (3ch) — 추후

cam0 단독 H.264/H.265 비교는 완료 (`07_storage_capacity.md` §4, **H.264** 채택).  
아래는 **3ch 동시 + YOLO live(`gpu_phase3`) + NVENC** 조건에서 재측정 예정 (`00_project_plan.md` Phase 4 §4.1).

### 3.1 예정 실행 (초안)

```bash
source venv.sh
# TBD: 3ch 부하 하에서 코덱 비교 — cam-acq-codec-profile 확장 또는 yolo-live + event 녹화 구간 측정
uv run cam-acq-codec-profile --camera-index 0 \
  --output ./healthcheck/codec_profile_3ch.json
```

### 3.2 측정 항목 (템플릿)

| 항목 | H.264 | H.265 |
|------|-------|-------|
| 3ch 동시 NVENC frame drop | | |
| VRAM peak (MB) | | |
| NVENC util peak (%) | | |
| 동일 구간 file size (MB) | | |
| `ENCODING_CODEC` 최종 권고 | | |

### 3.3 결과

_측정 후 기입._

---

## 4. R3 — YOLO 1h soak (3ch) — 추후

`11_field_pending_work.md` §3.1. R1·R2와 별도이나 ring overflow·fps는 본 문서 §2.5와 교차 확인.

```bash
nohup uv run cam-acq-yolo-soak --duration 3600 --no-record \
  --output ./healthcheck/yolo_soak_3ch.json \
  > ./healthcheck/yolo_soak_3ch.log 2>&1 &
```

_결과 섹션은 soak 완료 후 추가._

---

## 5. 관련 문서

| 문서 | 내용 |
|------|------|
| `07_storage_capacity.md` | 용량·ring 추정식, cam0 코덱 단독 실측 |
| `11_field_pending_work.md` | 현장 일정 (soak, codec) |
| `12_debayer_3ch_strategy.md` | YOLO `gpu_phase3` 3ch fps (~20) |
| `00_project_plan.md` | Phase 4.9, Phase 6 T12 |
