# System Architecture

구조 변경 시 본 문서와 `00_project_plan.md`를 함께 갱신한다.

## 1. 개요

| 항목 | 값 |
|------|-----|
| OS | Ubuntu 24.04 |
| GPU | RTX 4070 Ti Super 16GB |
| RAM | 32GB |
| 카메라 | 3대 (4K@23fps, 2.5GigE) |
| 시간 동기화 | **host monotonic** + `TimestampReset` 세션 앵커 (PTP 미지원) |
| AI | YOLOv8m + DeepStream nvinfer |
| Encode | NVENC HW (H.265 or H.264, Phase 4 결정) |

## 2. 컴포넌트 다이어그램

```mermaid
flowchart TB
    subgraph env [Config]
        DOTENV[".env"]
    end

    subgraph cam [Camera Layer]
        CM[CameraManager\ncamera_index 0-based]
        TSM[TimeSyncManager\nhost clock + TimestampReset]
        GRAB[Grab Thread × N]
        RB[(Bayer 4K RAM Ring Buffer)]
        CM --> TSM --> GRAB --> RB
    end

    subgraph ds [DeepStream GPU]
        DEBAYER[nvvideoconvert\nBayer→NV12]
        PRE[Resize]
        YOLO[YOLOv8m nvinfer]
        RB --> DEBAYER
        RB --> PRE --> YOLO
    end

    subgraph rec [Recording]
        RC[RecordingController\n전 채널 동시]
        ENC[NVENC HW\nH.265 or H.264]
        META["Metadata\n.json + .frames.jsonl"]
        YOLO -->|trigger| RC
        DEBAYER --> RC
        RC --> ENC --> META
        META --> STOR[(STORAGE_PATH\nor STORAGE_PATH_SUB)]
        SM[StorageManager\nFIFO + path fallback]
        STOR --> SM
    end

    subgraph ui [Monitoring Local]
        COL[Data Collector\n수신 FPS 23]
        SYS[Host Metrics\nCPU RAM GPU temp]
        WEB[Dashboard\n≤ UI_MAX_DISPLAY_FPS]
        PRE -->|resize only| COL
        YOLO --> COL
        CM --> COL
        SM --> COL
        SYS --> COL
        COL --> WEB
    end

    DOTENV --> CM
    DOTENV --> RC
    DOTENV --> WEB
```

## 3. 데이터 흐름

### 3.1 취득 → Detection

```
Camera (Bayer 4K)
  → TimeSyncManager (세션 시작: TimestampReset + host_t0 앵커)
  → Grab Thread
  → RAM Ring Buffer (pre-buffer, Bayer raw)
  → nvvideoconvert (resize branch) → YOLOv8m
  → detection event (bbox_resized → bbox_original)
```

프레임 메타: `host_recv_us` + `camera_ts_us` (카메라 tick, 1 GHz). 상세: `05_metadata_schema.md`

### 3.2 녹화 (trigger 시)

```
RAM Ring Buffer (Bayer 4K, pre+event+post)
  → GPU debayer (nvvideoconvert) → NV12 4K
  → NVENC (H.265 or H.264, HW)
  → .mp4 + .json + .frames.jsonl → STORAGE_PATH (불가 시 STORAGE_PATH_SUB)
```

**Bayer를 NVENC에 직접 넣지 않는다.**

녹화 pre/post window는 **호스트 monotonic** 기준 (3채널 동시 trigger). PTP 없음.

### 3.3 시간 동기화 (PTP 미사용)

현장 확인: PTP GenICam **미구현**, 4-port L2 분리 → 카메라 간 sync 불가.

| 역할 | 소스 | 용도 |
|------|------|------|
| 이벤트·녹화 경계 | host `monotonic` | detection → 전 채널 record window |
| 채널 내 순서·드랍 | `frame.timestamp` (camera tick) | healthcheck `timestamp_monotonic` |
| 세션 앵커 | `TimestampReset` + `host_t0` | 채널별 상대 0점 (`timestamp_test --reset`) |

```
세션 시작 → reset_all_timestamps() (순차) → host_t0 + (cam_i, ts0_i) 기록
프레임 수신 → host_recv_us, camera_ts_us, frame_id → .frames.jsonl
```

TimeSyncManager는 PTP를 호출하지 않는다. 상세: `09_network_topology.md`

### 3.4 Monitoring

```
Resize branch (960×540)
  → Collector @ 23fps (FPS, detection, storage, camera status)
HostMetricsSampler @ SYSTEM_METRICS_POLL_SEC
  → CPU, RAM, GPU util, VRAM, GPU temperature (NVML)
  → WebSocket/MJPEG + REST
  → Dashboard: 시스템 패널 + 카메라 그리드 @ ≤ UI_MAX_DISPLAY_FPS
```

상세: `10_monitoring_design.md`

## 4. IPC

| 경로 | 방식 |
|------|------|
| Grab → Buffer | shared memory / ring buffer |
| Detection → Recording | event queue (Python) |
| Collector → Web | in-process / WebSocket |

## 5. 모듈 ↔ 언어

| 모듈 | 언어 |
|------|------|
| Orchestration | Python |
| TimeSyncManager | Python (host clock, TimestampReset) |
| Camera grab | Python (P1) / C (병목 시) |
| Debayer / Resize / YOLO | DeepStream (C/CUDA) |
| NVENC | GStreamer/DeepStream |
| Storage / Web | Python |

상세: `03_language_split.md`

## 6. 카메라 인덱스

```
camera_index 0 → CAMERA0_IP
camera_index 1 → CAMERA1_IP
camera_index 2 → CAMERA2_IP
```

인덱스는 0부터. IP last octet과 무관.

## 7. 코덱 결정 (Phase 4)

NVENC HW로 H.265 vs H.264 프로파일링 후 `.env` 확정.  
절차: `00_project_plan.md` Phase 4 §4.1

## 8. 관련 문서

| 문서 | 내용 |
|------|------|
| `01_sdk_feasibility.md` | Demosaic, SDK, timestamp |
| `02_streaming_design.md` | UI FPS |
| `05_metadata_schema.md` | 메타 파일, time_sync |
| `06_yolo_build_porting_guide.md` | YOLO |
| `07_storage_capacity.md` | 용량 |
| `08_ssh_healthcheck_guide.md` | 원격 검증 |
| `09_network_topology.md` | 시간 동기화, NIC |
| `10_monitoring_design.md` | Dashboard, host metrics |
