# cam_acq 시스템 구축 계획

## 1. 프로젝트 개요


| 항목     | 내용                                                                 |
| ------ | ------------------------------------------------------------------ |
| 목적     | 3대 4K GigE 카메라 실시간 취득 → Human Detection → 이벤트 기반 녹화 → Web 모니터링     |
| 플랫폼    | Ubuntu 24.04, C + Python (uv/venv), NVIDIA DeepStream 9.0 (native) |
| GPU    | RTX 4070 Ti Super 16GB                                             |
| RAM    | 32GB                                                               |
| 실행 주체  | Python (전체 오케스트레이션)                                                |
| SDK    | `sdk/Galaxy_camera/c`, `sdk/Galaxy_camera/python`                  |
| SDK 문서 | `sdk/Galaxy_camera/c/doc`                                          |
| 설정     | `.env`                                                             |


### Image Processing Flow

```
카메라 취득 (Bayer)
  → Pre-buffer (Bayer raw Full 4K, RAM)
  → Resize → Human Detection (GPU)
  → Debayer → NV12 → NVENC (녹화, trigger 시)
  → Resize 썸네일 → Monitoring (수신 FPS)
```

### 환경 현황


| 항목                                       | 상태                           |
| ---------------------------------------- | ---------------------------- |
| Viewer 3대 연결                             | 완료                           |
| Test env (2ch PoC)                       | ✅ 완료 (2026-06-30)             |
| 운영 환경                                    | 카메라 **3대** — live·recording 검증 완료 (2026-06-30) |
| Jumbo/MTU                                | 설정 완료                        |
| Socket buffer (`SetSocketBufferSize.sh`) | 적용 완료                         |
| 네트워크 (4-port 직결)                        | `09_network_topology.md`       |
| PTP                                      | **HW 미지원** (test 2대) → `host_clock_sync` |
| 24h 에이징                                  | 미진행                          |
| Ubuntu 24.04                             | 시스템 driver가 22.04에서 미동작하여 사용 |


---

## 2. 확정 사항 요약


| 항목         | 결정                                                      |
| ---------- | ------------------------------------------------------- |
| 카메라 인덱스    | **0-based** (`CAMERA0_IP` = 인덱스 0, IP octet과 무관)        |
| Pre-buffer | **Full 4K Bayer raw** (RAM ring buffer)                 |
| Buffer 시간  | `RECORDING_BUFFER_SEC`: ring **pre** 용량 + **event 침묵 종료** 대기 (아래 §3.2) |
| 저장 경로      | `STORAGE_PATH` (primary) + `STORAGE_PATH_SUB` (fallback) |
| 녹화 범위      | **전 채널 동시** (3대)                                        |
| Demosaic   | Pre-buffer는 Bayer 유지, **녹화 encode 직전 GPU debayer 필수**   |
| 코덱         | **NVENC HW** 사용, H.265 vs H.264는 **Phase 4 프로파일링 후 결정** |
| Detection  | YOLOv8m (고정확도), TensorRT engine 별도 build                |
| Streaming  | Resize 썸네일만, 수신 FPS 유지, `UI_MAX_DISPLAY_FPS`로 표시 상한     |
| Monitoring | 카메라 FPS·detection·storage + **CPU/RAM/GPU/온도** Dashboard (`10_monitoring_design.md`) |
| 카메라 파라미터 | **런타임 PATCH** — ExposureTime/Auto, Gain/Auto, AcquisitionFrameRate, GammaMode/Gamma (`01_sdk_feasibility.md` §3.3, `--with-monitoring`) |
| 메타데이터      | `.json` (session) + `.frames.jsonl` (프레임) 분리            |
| DeepStream | **네이티브** (DS 9.0, Ubuntu 24.04 공식 지원)                   |


---

## 3. Phase 계획

### Phase 0 — 선행 검토 및 환경


| ID  | 작업                  | 산출물                      |
| --- | ------------------- | ------------------------ |
| 0.1 | SDK 기능 검토           | `01_sdk_feasibility.md`  |
| 0.2 | Streaming 설계        | `02_streaming_design.md` |
| 0.3 | Language 배치         | `03_language_split.md`   |
| 0.4 | 아키텍처 확정             | `architecture.md`        |
| 0.5 | NVIDIA/DS/Galaxy 설치 | `04_install_guide.md`    |
| 0.6 | PTP 카메라 test        | **완료** — PTP 미지원, host_clock_sync |


---

### Phase 1 — 기반 + 2대 검증


| ID  | 작업                             | 검증                            |
| --- | ------------------------------ | ----------------------------- |
| 1.1 | uv 프로젝트, `.env.example`, 설정 로더 | ✅ `uv sync`                     |
| 1.2 | 일별 로깅                          | ✅ `LOG_PATH/YYYY-MM-DD.log`     |
| 1.3 | Python gxipy 2대 동시 grab        | ✅ healthcheck PASS (22.6+ fps)  |
| 1.4 | PTP 부정 test (`ptp_test`)       | ✅ PTP 미지원, host_clock_sync   |
| 1.5 | 테스트용 원본 프레임 저장                 | ✅ `samples/cam*_last.jpg`       |
| 1.6 | `grab_healthcheck` CLI           | ✅ 현장 PASS                     |
| 1.7 | `timestamp_test` (`TimestampReset`) | ✅ reset 지원 확인 (현장)        |


**통과 기준:** 2대에서 23fps 안정 취득 (healthcheck PASS) → **Phase 1 완료**, Phase 2 진행.

**원격 확인:** SSH + `grab_healthcheck` JSON 리포트. 상세는 `08_ssh_healthcheck_guide.md`.

---

### Phase 2 — 카메라 모듈 (3대 운영)


| ID  | 작업                                                 |
| --- | -------------------------------------------------- |
| 2.1 | 3대 IP(0-based) 오픈, 4ch NIC                         | ✅ (2026-06-30) — cam0/1/2 online |
| 2.2 | TimeSyncManager (host clock + `TimestampReset` 세션 앵커) | ✅ `grab_healthcheck` 연동 |
| 2.3 | GigE offline recovery (grab + **yolo-live·recording**) | ✅ E2E PASS (2026-06-30, 3ch) — `13_gige_disconnect_recovery.md` |
| 2.4 | `SetSocketBufferSize.sh` 적용                        | ✅ `socket_buffer_check` PASS (원격) |
| 2.5 | 2대 PoC 병목 시 C grab 모듈 도입                           | 보류 (3ch grab 병목 없음) |
| 2.6 | 1시간 soak test (`grab_healthcheck --duration 3600`) | ✅ 2대 PASS — 3ch grab-only는 선택 (`11_field_pending_work.md` §3.3) |


---

### Phase 3 — DeepStream + YOLO


| ID  | 작업 | 코드 | 검증 (현장/테스트) |
| --- | --------------------------------------- | --- | --- |
| 3.1 | DeepStream multi-source 파이프라인 (live) | ✅ `cam-acq-yolo-live` | ✅ 3ch (2026-06-30) |
| 3.2 | YOLOv8m → ONNX → TensorRT engine build (`batch=NUM_CAMERAS`) | ✅ | ✅ `batch=3` engine |
| 3.3 | bbox 역변환 (resize → 원본 4K) | ✅ `bbox.py`, `events.py` | ✅ unit |
| 3.4 | overlay 테스트 영상 저장 (live) | ✅ MP4 finalize·stride 수정 | ✅ 2ch `yolo_person_test.mp4`; **3ch 1h soak 추후** (`11_field_pending_work.md` §3.1) |
| 3.5 | nvinfer meta → `RecordingTrigger` | ✅ `gst_meta.py` probe | ✅ 3ch event trigger (`yolo_live_3ch_gpu.json`) |
| 3.6 | GPU debayer (Phase 3 경로) | ✅ `gpu_phase3` in yolo-live | ✅ 3ch ~20fps (`gpu_phase3`, 2026-06-30) |
| 3.x | **3ch 전환** (`NUM_CAMERAS=3`) | ✅ | dashboard live + event recording |
| 3.y | per-camera 혼합 debayer (GPU 2 + CPU 1) | 보류 | 3ch `gpu_phase3` PASS — 채택 안 함 |

**Phase 3 현장 검증 완료 (2026-06-30, 3ch).** 남음: 3ch YOLO 1h soak — `11_field_pending_work.md` §3.1.

상세: `06_yolo_build_porting_guide.md`

---

### Phase 4 — Recording


| ID  | 작업 | 코드 | 검증 |
| --- | ------------------------------------------------ | --- | --- |
| 4.1 | Full 4K Bayer pre-buffer (RAM ring) | ✅ `recording/buffer.py` | ✅ unit |
| 4.2 | Bayer → debayer → NVENC | ✅ `recording/gst_encode.py` (`bayer2rgb` + `cudaupload` + `nvcuda*enc`) | ✅ 3ch manual (`*_manual.mp4`, 2026-06-30) |
| 4.3 | Human detection + auto trigger | ✅ `yolo-live` + `RecordingController` | ✅ 3ch event 녹화 (`152223_cam{0,1,2}_seg0000.mp4`) |
| 4.4 | Event 침묵 종료 + manual start/stop | ✅ `RecordingTrigger` + `RecordingController` | ✅ 3ch 운영 중 event + manual |
| 4.5 | Split recording | ✅ segment split in controller | ✅ 3ch `interval`·`gige_disconnect` split |
| 4.6 | H.265 vs H.264 프로파일링 | **cam0 ✅** → **H.264** | cam0 단독 완료; **3ch 부하 재측정 추후** (`11_field_pending_work.md` §3.4) |
| 4.7 | 메타데이터 (`.json` + `.frames.jsonl`) | ✅ `recording/metadata.py` | ✅ 3ch recordings |
| 4.8 | StorageManager (FIFO, fallback) | ✅ `recording/storage.py` | ✅ unit + T7 FIFO_DELETE (2026-06-30) |
| 4.9 | RAM/VRAM 실측 | **2ch ✅**; **3ch ✅** buffer 2s (`15_3ch_resource_profiling.md` §2) | `cam-acq-memory-profile` |


#### 4.1 코덱 결정 절차 (H.265 vs H.264)

HW encoding(NVENC) 전제. Phase 4 초기에 아래를 측정하고 결정한다.

**측정 조건**

- 3채널 동시 녹화 (전 채널 trigger)
- 4K@23fps, Full 4K debayer → NV12 → NVENC
- Detection(YOLOv8m) + resize stream 동시 가동

**측정 항목**


| 항목                  | 도구                             |
| ------------------- | ------------------------------ |
| GPU 사용률 / VRAM      | `nvidia-smi dmon`              |
| NVENC 세션 수 / 인코딩 지연 | `nvidia-smi enc-stats` 또는 앱 로그 |
| CPU 사용률             | `htop`                         |
| 파일 크기 (동일 구간)       | H.265 vs H.264 비교              |
| 화질                  | 육안 + PSNR/SSIM (선택)            |
| 디코딩 호환              | VLC/ffprobe                    |


**결정 기준**


| 우선  | 조건                                    |
| --- | ------------------------------------- |
| 1   | 3ch 동시 NVENC 시 프레임 드랍 0, VRAM 16GB 이내 |
| 2   | 동일 화질 기준 파일 크기 (H.265 유리 시 H.265)     |
| 3   | 인코딩 지연·발열 허용 범위                       |


**결과 반영**

- `.env`의 `ENCODING_CODEC` 최종값 확정
- `07_storage_capacity.md` 용량 표 갱신
- 결정 사유를 `docs/` 또는 로그에 기록

---

### Phase 5 — Monitoring


| ID  | 작업 | 코드 | 검증 |
| --- | --- | --- | --- |
| 5.1 | Data Collector (FPS, detection, storage, 연결, pre-buffer, timesync) | ✅ `DashboardCollector` + `PipelineHooks` | `cam-acq-yolo-live --with-monitoring` |
| 5.2 | Host metrics — CPU, RAM, GPU, NVENC/NVDEC, VRAM, 온도, RSS, disk I/O, NIC | ✅ `host_metrics.py` | `cam-acq-monitoring` |
| 5.3 | Dashboard UI — 시스템 패널 + 카메라 카드(스트림/bbox) + storage | ✅ `static/index.html` | WebSocket |
| 5.4 | 수동 녹화 UI (start/stop, 진행 시간) | ✅ | `POST /api/recording/trigger`, `POST /api/recording/stop` |
| 5.5 | REST `/api/health`, `/api/system/metrics`, `/api/cameras/{id}/stats` | ✅ | curl |
| 5.6 | WebSocket `/api/ws/dashboard` | ✅ | |
| 5.7 | 썸네일 스트림 (MJPEG) | ✅ | `GET /api/stream/{camera_index}` |
| 5.8 | 카메라 파라미터 설정 UI (별도 설정 창 + Apply → PATCH) | ✅ | REST `GET/PATCH .../params` + `--with-monitoring` |

상세: `10_monitoring_design.md`


---

### Phase 7 — 운영 보강 (계획)

3ch 운영 안정화 이후 로깅·진단·UI·설정 영속성. 상세: `14_operations_enhancements.md`.


| ID  | 작업 | 검증 |
| --- | --- | --- |
| 7.1 | System log — WARNING+ 일별, pipeline/dashboard 분리 | 로그 파일 경로·레벨 확인 |
| 7.2 | Raw BMP(debayer) 저장 script (`scripts/`) | 샘플 BMP·raw 생성 |
| 7.3 | Dashboard event 녹화 표시 (`event`) | event trigger 시 footer 문구 |
| 7.4 | 시간당 system resource peak — dashboard + JSONL | 1h bucket·peak max |
| 7.5 | 카메라 setting 영속화·기동 시 apply | 전원 cycle 후 설정 유지 |


---

### Phase 6 — 통합 테스트


| #   | 시나리오                       | 기대 결과 | 상태 (2026-06-30) |
| --- | -------------------------- | -------------------------------- | --- |
| T1  | Human detection trigger 녹화 | 3채널 파일 생성 | ✅ `152223_cam{0,1,2}_seg0000.mp4` |
| T2  | 수동 start → stop              | `*_manual.mp4` + 메타 생성 | ✅ `152217_*_manual.mp4` ×3 |
| T3  | Pre-buffer                 | 이벤트 **이전** 영상 포함 (`RECORDING_BUFFER_SEC`) | ✅ event recording 운영 중 |
| T4  | Event 침묵 tail            | 마지막 person 검출 후 **연속** `RECORDING_BUFFER_SEC` 무검출 시 종료 | ✅ event recording 운영 중 |
| T5  | Split interval             | 파일 분할 시간 일치 | ✅ `split.reason: interval` (300s) |
| T6  | 메타데이터                      | `.json` + `.frames.jsonl` 유효성 | ✅ recordings 메타 존재 |
| T7  | FIFO_DELETE                | 오래된 파일부터 삭제 | ✅ (`010304` manual 삭제 확인) |
| T8  | FIFO_REJECT                | 임계치 이후 저장 거부 | ❌ 미구현 |
| T9  | 카메라 disconnect | dashboard 재연결 + recording `gige_disconnect` split | ✅ 3ch — `13_gige_disconnect_recovery.md` |
| T10 | TimeSync drift             | 세션 앵커·timestamp offset 로그 | ✅ 2ch 검증; 3ch 운영 중 |
| T14 | Host metrics API           | CPU/RAM/GPU/온도 `/api/system/metrics` 유효 | ✅ `/api/health` PASS |
| T11 | 전 채널 동시 trigger            | 3개 파일 동시 생성 | ✅ `152223` 동일 시각 3파일 |
| T12 | Pre-buffer RAM 실측          | 32GB 이내 확인 | ✅ RSS 7.9 GB (`15_3ch_resource_profiling.md` §2) |
| T13 | 녹화 영상 재생                   | debayer 후 H.26x 정상 재생 (색상 깨짐 없음) | ✅ 육안 확인 |


---

## 4. 문서 목록


| 파일                               | 용도                 |
| -------------------------------- | ------------------ |
| `00_project_plan.md`             | 본 문서               |
| `01_sdk_feasibility.md`          | SDK 기능 검토          |
| `02_streaming_design.md`         | 스트리밍 설계            |
| `03_language_split.md`           | 언어 배치              |
| `04_install_guide.md`            | 설치 가이드             |
| `05_metadata_schema.md`          | 메타데이터 명세           |
| `06_yolo_build_porting_guide.md` | YOLO build/porting |
| `07_storage_capacity.md`         | 저장 용량 계산           |
| `08_ssh_healthcheck_guide.md`    | SSH 원격 확인          |
| `09_network_topology.md`         | 4-port NIC, netplan  |
| `10_monitoring_design.md`        | Dashboard, CPU/GPU 메트릭 |
| `11_field_pending_work.md`       | 현장 대기 작업 (3대, recovery, 1h soak) |
| `13_gige_disconnect_recovery.md` | GigE disconnect — dashboard 재연결, recording split/resume 스펙 |
| `14_operations_enhancements.md`  | 운영 보강 — system log, BMP script, event UI, resource peak, camera params 영속 |
| `15_3ch_resource_profiling.md`   | 3ch RAM/VRAM·코덱 실측 기록 |
| `architecture.md`                | 아키텍처 diagram       |


구조 변경 시 `architecture.md` 및 관련 문서를 함께 갱신한다.

---

## 5. 리스크


| 리스크                               | 완화                              |
| --------------------------------- | ------------------------------- |
| Pre-buffer RAM (~5.7GB, 3대 Bayer) | Phase 4 실측, 32GB 모니터링           |
| Bayer 직접 encode 시 색상 깨짐           | GPU debayer → NV12 → NVENC (필수) |
| 3ch NVENC + YOLO VRAM             | Phase 4 코덱/프로파일링                |
| PTP / 카메라 간 sync                  | PTP 미지원 → host clock + `TimestampReset` (`09_network_topology.md`) |
| Test 2대 / 운영 3대                   | 3ch live·recording·RAM 실측 완료; **1h soak·codec** — `15_3ch_resource_profiling.md` |


