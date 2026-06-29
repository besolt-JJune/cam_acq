# 저장 용량 계산

3채널 동시 녹화 기준. 코덱은 **NVENC HW** 전제.  
최종 코덱(H.265 vs H.264)은 Phase 4 프로파일링 후 확정 — 아래는 **양쪽 추정치** 모두 제시.

## 1. 전제

| 항목 | 값 |
|------|-----|
| 카메라 | 3대 (운영) |
| 해상도 | 3840×2160 |
| FPS | 23 |
| 녹화 | 전 채널 동시, 이벤트 트리거 |
| 인코딩 | Bayer → GPU debayer → NV12 → **NVENC** |
| usable 용량 | 활성 경로 디스크 기준: `disk_total × STORAGE_FULL_PERCENTAGE / 100` (메타 ~5% 차감 권장) |

### 1.1 저장 경로 (`STORAGE_PATH` / `STORAGE_PATH_SUB`)

| 변수 | 역할 |
|------|------|
| `STORAGE_PATH` | **primary** — 운영 녹화 저장소 (예: SSD mount `/data/recordings`) |
| `STORAGE_PATH_SUB` | **fallback** — primary를 쓸 수 없을 때 임시 저장 경로 |

**primary 사용 불가 조건 (예):** mount 미완료, 디렉터리 없음, 쓰기 권한 없음, 디스크 full로 reject.

```
시작 / 녹화 전
  → STORAGE_PATH 사용 가능? → yes: primary
                           → no:  STORAGE_PATH_SUB (로그·메타에 active_path 기록)
```

- Phase 4 `StorageManager`가 활성 경로를 선택하고 FIFO·용량 계산에 반영한다.
- fallback은 **임시** 용도; primary 복구 후 신규 녹화는 primary로 전환 (기존 fallback 파일은 수동 이관 또는 FIFO 정리).
- 용량 표(§4)는 **활성 경로가 가리키는 디스크** 기준으로 해석한다.

```bash
STORAGE_PATH=/data/recordings
STORAGE_PATH_SUB=./recordings
```

> **연속 녹화(worst case):** 사람이 항상 검출되어 3채널이 끊김 없이 녹화될 때의 상한.  
> 실제 운영은 이벤트 빈도에 따라 훨씬 길게 저장된다.

## 2. Bitrate 가정 (4K@23fps, NVENC)

| 품질 | H.264 (채널당) | H.265 (채널당) | 3채널 합산 |
|------|----------------|----------------|-----------|
| Standard | 12 Mbps | 8 Mbps | 36 / 24 Mbps |
| High | 20 Mbps | 12 Mbps | 60 / 36 Mbps |
| Very High | 35 Mbps | 20 Mbps | 105 / 60 Mbps |

`.env` 추정용 (Phase 4 전 임시):

```bash
ENCODING_BITRATE_MBPS=12    # 채널당, H.265 high 기준
# H.264 사용 시 ~20 권장
```

## 3. 계산식

```
usable_bytes = disk_total_bytes × (STORAGE_FULL_PERCENTAGE / 100) × 0.95

total_bitrate_bps = ENCODING_BITRATE_MBPS × 1_000_000 × NUM_CAMERAS

max_seconds = usable_bytes × 8 / total_bitrate_bps
max_hours   = max_seconds / 3600
max_days    = max_hours / 24
```

## 4. 예시 (`STORAGE_FULL_PERCENTAGE=90`, 메타 5% 차감)

### H.265 (Phase 4 후보)

| 디스크 | 품질 | 3ch 합산 | **최대 연속 녹화** |
|--------|------|----------|-------------------|
| 1 TB | Standard (24 Mbps) | 3.0 MB/s | **≈ 77시간 (3.2일)** |
| 1 TB | High (36 Mbps) | 4.5 MB/s | **≈ 51시간 (2.1일)** |
| 2 TB | High (36 Mbps) | 4.5 MB/s | **≈ 103시간 (4.3일)** |
| 4 TB | High (36 Mbps) | 4.5 MB/s | **≈ 207시간 (8.6일)** |

### H.264 (비교)

| 디스크 | 품질 | 3ch 합산 | **최대 연속 녹화** |
|--------|------|----------|-------------------|
| 1 TB | Standard (36 Mbps) | 4.5 MB/s | **≈ 51시간 (2.1일)** |
| 1 TB | High (60 Mbps) | 7.5 MB/s | **≈ 31시간 (1.3일)** |
| 2 TB | High (60 Mbps) | 7.5 MB/s | **≈ 62시간 (2.6일)** |
| 4 TB | High (60 Mbps) | 7.5 MB/s | **≈ 124시간 (5.2일)** |

동일 화질 기준 H.265가 용량 30~50% 절감. Phase 4에서 GPU 부하와 함께 최종 선택.

### 4.1 Phase 4.6 cam0 실측 (2026-06-29)

`cam-acq-codec-profile` — cam0 단독, **4024×3036**@23fps, `ENCODING_BITRATE_MBPS=12`, `RECORDING_SPLIT_INTERVAL_SEC=360`, buffer 5s.

스케줄: duration **370s** (= 5 + 360 + 5), trigger-at **5s**, split 경계마다 5s 청크 증분 인코딩.

| 코덱 | 총 프레임 | 총 파일 | encode 처리량 | NVENC peak % |
|------|-----------|---------|---------------|--------------|
| H.264 | 8,493 | **734 MB** (seg00 724M + seg01 9.4M) | 41 fps | 28 |
| H.265 | 8,493 | **780 MB** (seg00 770M + seg01 10M) | 72 fps | 50 |

H.265/H.264 크기 비율 ≈ **1.06** (동일 12 Mbps target, 360s+10s 윈도우).

**결정 (2026-06-29):** 3ch+YOLO integration test 전 **H.264** (`ENCODING_CODEC=H264`). NVENC headroom 우선; H.265는 2~3ch 동시 부하 재검증 후.

**미완:** 2ch 동시 + YOLO resize 부하, 운영 3ch integration test.

## 5. Pre-buffer RAM (Bayer, 녹화와 별도)

### 5.1 Phase 4.9 실측 (2026-06-29, 2ch)

`cam-acq-memory-profile` — 4024×3036 BayerRG8, `RECORDING_BUFFER_SEC=5`, ring capacity 350 frames/ch.

| 항목 | cam0 | cam1 | 합계 |
|------|------|------|------|
| ring (measured) | 4.0 GB | 4.0 GB | **8.0 GB** |
| process RSS peak | — | — | **10.8 GB** |
| system RAM peak | — | — | **13.8 GB** (46.9%) |
| VRAM peak (encode) | — | — | **559 MB** |

3ch 추정 (선형): ring ≈ **12.0 GB**, RSS ≈ **16 GB** — 32 GB RAM 내 수용 가능 (YOLO·OS 여유 별도).

### 5.2 추정식 (참고)

```
1 frame  ≈ width × height  (Bayer8; 실측 4024×3036 ≈ 11.7 MB)
capacity = ring_capacity_frames(fps, RECORDING_BUFFER_SEC)  # 3× buffer + margin
per_cam  = capacity × width × height
```

## 6. 이벤트 기반 실사용 (참고)

```
effective_days ≈ max_continuous_days / duty_cycle
duty_cycle     = (하루 실제 녹화 시간) / 86400
```

예: worst 4.3일(2TB H.265 high), 하루 2시간만 3ch 녹화 → `4.3 / (2/24) ≈ 52일`

## 7. Phase 4 연동

코덱 결정 후:

1. `.env` `ENCODING_CODEC`, `ENCODING_BITRATE_MBPS` 확정
2. StorageManager에 잔여 녹화 시간 추정 로직 반영
3. 본 문서 표 갱신

상세 절차: `00_project_plan.md` Phase 4 §4.1

## 8. 관련 문서

- `00_project_plan.md`
- `01_sdk_feasibility.md` — debayer → NVENC
