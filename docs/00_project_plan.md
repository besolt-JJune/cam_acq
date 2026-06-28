# cam_acq 시스템 구축 계획

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 목적 | 3대 4K GigE 카메라 실시간 취득 → Human Detection → 이벤트 기반 녹화 → Web 모니터링 |
| 플랫폼 | Ubuntu 24.04, C + Python (uv/venv), NVIDIA DeepStream 9.0 (native) |
| GPU | RTX 4070 Ti Super 16GB |
| RAM | 32GB |
| 실행 주체 | Python (전체 오케스트레이션) |
| SDK | `sdk/Galaxy_camera/c`, `sdk/Galaxy_camera/python` |
| SDK 문서 | `sdk/Galaxy_camera/c/doc` |
| 설정 | `.env` |

### Image Processing Flow

```
카메라 취득 (Bayer)
  → Pre-buffer (Bayer raw Full 4K, RAM)
  → Resize → Human Detection (GPU)
  → Debayer → NV12 → NVENC (녹화, trigger 시)
  → Resize 썸네일 → Monitoring (수신 FPS)
```

### 환경 현황

| 항목 | 상태 |
|------|------|
| Viewer 3대 연결 | 완료 |
| Test env | 카메라 **2대** |
| 운영 환경 | 카메라 **3대** |
| Jumbo/MTU | 설정 완료 |
| Socket buffer (`SetSocketBufferSize.sh`) | 미적용 → 설치 시 적용 |
| PTP | 카메라 test 후 확정 |
| 24h 에이징 | 미진행 |
| Ubuntu 24.04 | 시스템 driver가 22.04에서 미동작하여 사용 |

---

## 2. 확정 사항 요약

| 항목 | 결정 |
|------|------|
| 카메라 인덱스 | **0-based** (`CAMERA0_IP` = 인덱스 0, IP octet과 무관) |
| Pre-buffer | **Full 4K Bayer raw** (RAM ring buffer) |
| Buffer 시간 | `RECORDING_BUFFER_SEC` 단일 (pre/post 공용) |
| 저장 경로 | `STORAGE_PATH` 단일 |
| 녹화 범위 | **전 채널 동시** (3대) |
| Demosaic | Pre-buffer는 Bayer 유지, **녹화 encode 직전 GPU debayer 필수** |
| 코덱 | **NVENC HW** 사용, H.265 vs H.264는 **Phase 4 프로파일링 후 결정** |
| Detection | YOLOv8m (고정확도), TensorRT engine 별도 build |
| Streaming | Resize 썸네일만, 수신 FPS 유지, `UI_MAX_DISPLAY_FPS`로 표시 상한 |
| 메타데이터 | `.json` (session) + `.frames.jsonl` (프레임) 분리 |
| DeepStream | **네이티브** (DS 9.0, Ubuntu 24.04 공식 지원) |

---

## 3. Phase 계획

### Phase 0 — 선행 검토 및 환경

| ID | 작업 | 산출물 |
|----|------|--------|
| 0.1 | SDK 기능 검토 | `01_sdk_feasibility.md` |
| 0.2 | Streaming 설계 | `02_streaming_design.md` |
| 0.3 | Language 배치 | `03_language_split.md` |
| 0.4 | 아키텍처 확정 | `architecture.md` |
| 0.5 | NVIDIA/DS/Galaxy 설치 | `04_install_guide.md` |
| 0.6 | PTP 카메라 test | test 결과 기록 |

---

### Phase 1 — 기반 + 2대 검증

| ID | 작업 | 검증 |
|----|------|------|
| 1.1 | uv 프로젝트, `.env.example`, 설정 로더 | `uv sync` |
| 1.2 | 일별 로깅 | `LOG_PATH/YYYY-MM-DD.log` |
| 1.3 | Python gxipy 2대 동시 grab | healthcheck PASS |
| 1.4 | PTP feature read test | `PtpEnable`, `PtpStatus` 접근 |
| 1.5 | 테스트용 원본 프레임 저장 | 파일 생성 |
| 1.6 | `grab_healthcheck` CLI | `08_ssh_healthcheck_guide.md` |

**통과 기준:** 2대에서 23fps 안정 취득 (healthcheck PASS) → Phase 2 진행.

**원격 확인:** SSH + `grab_healthcheck` JSON 리포트. 상세는 `08_ssh_healthcheck_guide.md`.

---

### Phase 2 — 카메라 모듈 (3대 운영)

| ID | 작업 |
|----|------|
| 2.1 | 3대 IP(0-based) 오픈, 4ch NIC |
| 2.2 | PTP TimeSyncManager (test 결과 반영) |
| 2.3 | GigE offline recovery |
| 2.4 | `SetSocketBufferSize.sh` 적용 |
| 2.5 | 2대 PoC 병목 시 C grab 모듈 도입 |
| 2.6 | 1시간 soak test (`grab_healthcheck --duration 3600`) |

---

### Phase 3 — DeepStream + YOLO

| ID | 작업 |
|----|------|
| 3.1 | DeepStream 9.0 multi-source 파이프라인 (3ch) |
| 3.2 | YOLOv8m → ONNX → TensorRT engine build |
| 3.3 | bbox 역변환 (resize → 원본 4K) |
| 3.4 | overlay 테스트 영상 저장 |
| 3.5 | detection 이벤트 → Recording trigger |

상세: `06_yolo_build_porting_guide.md`

---

### Phase 4 — Recording

| ID | 작업 |
|----|------|
| 4.1 | Full 4K Bayer pre-buffer (RAM ring) |
| 4.2 | **녹화 경로: Bayer → GPU debayer → NV12 → NVENC** |
| 4.3 | Human detection + 수동 trigger |
| 4.4 | post-buffer (`RECORDING_BUFFER_SEC`) |
| 4.5 | Split recording (`RECORDING_SPLIT_INTERVAL_SEC`) |
| 4.6 | **코덱 결정: NVENC H.265 vs H.264 프로파일링** (§4.1) |
| 4.7 | 메타데이터 (`.json` + `.frames.jsonl`) |
| 4.8 | StorageManager (FIFO_DELETE / FIFO_REJECT) |
| 4.9 | RAM/VRAM 실측 (32GB / 16GB) |

#### 4.1 코덱 결정 절차 (H.265 vs H.264)

HW encoding(NVENC) 전제. Phase 4 초기에 아래를 측정하고 결정한다.

**측정 조건**

- 3채널 동시 녹화 (전 채널 trigger)
- 4K@23fps, Full 4K debayer → NV12 → NVENC
- Detection(YOLOv8m) + resize stream 동시 가동

**측정 항목**

| 항목 | 도구 |
|------|------|
| GPU 사용률 / VRAM | `nvidia-smi dmon` |
| NVENC 세션 수 / 인코딩 지연 | `nvidia-smi enc-stats` 또는 앱 로그 |
| CPU 사용률 | `htop` |
| 파일 크기 (동일 구간) | H.265 vs H.264 비교 |
| 화질 | 육안 + PSNR/SSIM (선택) |
| 디코딩 호환 | VLC/ffprobe |

**결정 기준**

| 우선 | 조건 |
|------|------|
| 1 | 3ch 동시 NVENC 시 프레임 드랍 0, VRAM 16GB 이내 |
| 2 | 동일 화질 기준 파일 크기 (H.265 유리 시 H.265) |
| 3 | 인코딩 지연·발열 허용 범위 |

**결과 반영**

- `.env`의 `ENCODING_CODEC` 최종값 확정
- `07_storage_capacity.md` 용량 표 갱신
- 결정 사유를 `docs/` 또는 로그에 기록

---

### Phase 5 — Monitoring

| ID | 작업 |
|----|------|
| 5.1 | Data Collector (수신 FPS, detection, PTP, storage) |
| 5.2 | Live Dashboard (최대 4ch, 로컬 폐쇄망) |
| 5.3 | 수동 녹화 트리거 UI |
| 5.4 | `/api/health` (healthcheck 지표 연동) |

---

### Phase 6 — 통합 테스트

| # | 시나리오 | 기대 결과 |
|---|----------|-----------|
| T1 | Human detection trigger 녹화 | 3채널 파일 생성 |
| T2 | 수동 trigger | 동일 |
| T3 | Pre-buffer | 이벤트 **이전** 영상 포함 |
| T4 | Post-buffer | 검출 종료 **이후** 영상 포함 |
| T5 | Split interval | 파일 분할 시간 일치 |
| T6 | 메타데이터 | `.json` + `.frames.jsonl` 유효성 |
| T7 | FIFO_DELETE | 오래된 파일부터 삭제 |
| T8 | FIFO_REJECT | 임계치 이후 저장 거부 |
| T9 | 카메라 disconnect | 로그 + 자동 복구 |
| T10 | PTP drift | offset 로그 기록 |
| T11 | 전 채널 동시 trigger | 3개 파일 동시 생성 |
| T12 | Pre-buffer RAM 실측 | 32GB 이내 확인 |
| T13 | 녹화 영상 재생 | debayer 후 H.26x 정상 재생 (색상 깨짐 없음) |

---

## 4. 문서 목록

| 파일 | 용도 |
|------|------|
| `00_project_plan.md` | 본 문서 |
| `01_sdk_feasibility.md` | SDK 기능 검토 |
| `02_streaming_design.md` | 스트리밍 설계 |
| `03_language_split.md` | 언어 배치 |
| `04_install_guide.md` | 설치 가이드 |
| `05_metadata_schema.md` | 메타데이터 명세 |
| `06_yolo_build_porting_guide.md` | YOLO build/porting |
| `07_storage_capacity.md` | 저장 용량 계산 |
| `08_ssh_healthcheck_guide.md` | SSH 원격 확인 |
| `architecture.md` | 아키텍처 diagram |

구조 변경 시 `architecture.md` 및 관련 문서를 함께 갱신한다.

---

## 5. 리스크

| 리스크 | 완화 |
|--------|------|
| Pre-buffer RAM (~5.7GB, 3대 Bayer) | Phase 4 실측, 32GB 모니터링 |
| Bayer 직접 encode 시 색상 깨짐 | GPU debayer → NV12 → NVENC (필수) |
| 3ch NVENC + YOLO VRAM | Phase 4 코덱/프로파일링 |
| PTP 미지원 | test 후 NTP fallback 검토 |
| Test 2대 / 운영 3대 | Phase 1~2는 2대, Phase 2 후 3대 전환 |
