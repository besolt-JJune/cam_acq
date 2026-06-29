# SDK 기능 검토 (Galaxy Camera SDK)

SDK 경로: `sdk/Galaxy_camera/c`, `sdk/Galaxy_camera/python`  
문서: `sdk/Galaxy_camera/c/doc/C_SDK_Programming_Reference_Manual.pdf`

## 1. 요구 기능 대응표

| 기능 | 구현 가능 | 구현 위치 | SDK 근거 |
|------|-----------|-----------|----------|
| 다중 카메라 스트리밍 | ✅ | SDK + 앱 | `GXUpdateAllDeviceList`, IP/MAC 오픈, `GXGetImage`/callback |
| 프레임 타임스탬프 | ✅ | 카메라 + SDK | `get_timestamp()`, `TimestampReset`, `TimestampLatchValue` |
| PTP 동기화 | ❌ **미지원** (현장 확인) | — | `PtpEnable`/`PtpStatus` 미구현; host clock 사용 |
| 연결 끊김/복구 | ✅ | SDK | `GXRegisterDeviceOfflineCallback`, `GxGigeRecovery` 샘플 |
| ExposureTime, Gain, FPS | ✅ | **카메라 내부** | GenICam feature (후처리 아님) |
| 해상도 (Width/Height) | ✅ | **카메라 내부** | `Width`, `Height`, ROI/Binning |
| Gamma | ✅ | **카메라 내부** (주) | `Gamma`, `GammaParam`; 호스트 LUT는 선택 |
| Demosaic | ✅ | SDK (CPU) / **GPU (운영)** | `DxImageProc`, `convert("RGB")` — §2 |
| 임의 Resize | ✅ | 호스트/GPU | OpenCV, DeepStream `nvvideoconvert` |
| 프레임 드랍 감지 | ✅ | SDK + 앱 | Frame ID gap, `nStatus`, 이벤트 feature |

## 2. Demosaic (Bayer → RGB/YUV)

### 2.1 SDK 지원

Galaxy SDK는 Bayer demosaic을 **지원**한다.

| 계층 | API |
|------|-----|
| C | `DxRaw8toRGB24`, `DxRaw16toRGB48` (`c/inc/DxImageProc.h`) |
| Python | `raw_image.convert("RGB")`, `ImageFormatConvert` |
| 알고리즘 | `DxBayerConvertType`: NEIGHBOUR, ADAPTIVE, NEIGHBOUR3, WEIGHT |

### 2.2 파이프라인에서의 역할 (확정)

**Bayer raw를 H.264/H.265에 직접 넣으면 안 된다.**

- 비디오 코덱(NVENC) 입력은 **NV12/YUV420** 등이 표준이다.
- Bayer를 grayscale/RGB처럼 encode하면 디코딩은 되지만 **색상이 깨져 보인다**.
- 표준 플레이어는 decode 후 demosaic을 수행하지 않는다.

| 구간 | 포맷 | Demosaic |
|------|------|----------|
| Pre/Post buffer (RAM) | Bayer raw Full 4K | **불필요** (원본 보존) |
| Detection | Resize된 YUV/RGB | DeepStream GPU 변환 |
| **녹화 encode** | Bayer → NV12 → NVENC | **필수 (GPU debayer)** |
| Phase 1 테스트 저장 | JPEG/PNG | SDK `convert("RGB")` 가능 |

### 2.3 구현 권장

```
Pre-buffer (Bayer 4K)
    → [GPU debayer: nvvideoconvert] → NV12 4K
    → [NVENC H.265 or H.264] → .mp4
```

- **운영:** DeepStream/GStreamer GPU 경로
- **디버그/테스트:** SDK `convert("RGB")` (CPU, 3×4K@23fps 상시 사용 비권장)

## 3. 카메라 파라미터 설정 가능 여부 (SDK)

초기 논의에서 **SDK/카메라가 파라미터를 설정할 수 있는지**만 확인했다.  
앱의 **Parameter Control**(런타임 변경·UI·`.env` 연동) 기능은 **별도 범위**이며, 본 절은 SDK·GenICam capability만 기록한다.

### 3.1 요약

| 파라미터 | SDK 설정 | 처리 위치 | GenICam feature (주) | SDK 샘플 |
|----------|----------|-----------|----------------------|----------|
| Exposure (노출) | ✅ | **카메라** | `ExposureTime`, `ExposureAuto`, `ExposureMode` | `GxSingleCamColor.py`, `GxViewer/ExposureGain` |
| Gain | ✅ | **카메라** | `Gain`, `GainAuto`, `GainSelector` | 동일 |
| FPS | ✅ | **카메라** | `AcquisitionFrameRate`, `AcquisitionFrameRateMode`, `CurrentAcquisitionFrameRate` (read) | `GxViewer/FrameRateControl` |
| 해상도 / ROI | ✅ | **카메라** | `Width`, `Height`, `OffsetX`, `OffsetY`, `BinningHorizontal/Vertical`, `SensorWidth/Height` | GenICam 표준 |
| Gamma | ✅ | **카메라** (주) | `GammaEnable`, `GammaMode`, `Gamma`; 호스트 LUT는 `GammaParam` + `DxGetGammatLut` | `GxSingleCamColor.py`, `GxViewer` |
| Pixel format | ✅ | **카메라** | `PixelFormat` | 앱 `.env` `PIXEL_FORMAT` (설정 시) |

모든 항목은 GenICam feature로 **카메라 펌웨어/센서에서 처리**된다. 후처리(OpenCV resize, GPU debayer 등)와 혼동하지 않는다.

### 3.2 파라미터별 상세

#### Exposure

| Feature | 타입 | 비고 |
|---------|------|------|
| `ExposureTime` | float (µs) | 수동 노출. `ExposureAuto=Off`일 때 `set()` 가능 |
| `ExposureAuto` | enum | `Off` / `Once` / `Continuous` |
| `ExposureMode` | enum | 모델별 (Timed 등) |
| `AutoExposureTimeMin/Max` | float | Auto 범위 (모델별) |

```python
cam.ExposureAuto.set(gx.GxAutoEntry.OFF)
cam.ExposureTime.set(10000.0)  # µs
```

#### Gain

| Feature | 타입 | 비고 |
|---------|------|------|
| `Gain` | float | 수동 gain. `GainAuto=Off`일 때 |
| `GainAuto` | enum | `Off` / `Once` / `Continuous` |
| `GainSelector` | enum | All / Red / Green / Blue (컬러) |

```python
cam.GainAuto.set(gx.GxAutoEntry.OFF)
cam.Gain.set(10.0)
```

#### FPS

| Feature | 타입 | 비고 |
|---------|------|------|
| `AcquisitionFrameRateMode` | enum | `On`이면 `AcquisitionFrameRate` 적용 |
| `AcquisitionFrameRate` | float | 목표 fps (모델·노출·해상도에 따라 상한 변동) |
| `CurrentAcquisitionFrameRate` | float (read) | 실측 fps |

운영 목표는 **23fps** (`NOMINAL_FPS`). 대역폭·노출 조합으로 상한이 달라질 수 있다 (`§7`).

```python
cam.AcquisitionFrameRateMode.set(gx.GxSwitchEntry.ON)
cam.AcquisitionFrameRate.set(23.0)
```

#### 해상도 / ROI

| Feature | 타입 | 비고 |
|---------|------|------|
| `Width`, `Height` | int | 현재 ROI 크기 |
| `OffsetX`, `OffsetY` | int | ROI 원점 |
| `WidthMax`, `HeightMax` | int (read) | 현재 binning 기준 최대 |
| `SensorWidth`, `SensorHeight` | int (read) | 센서 물리 해상도 |
| `BinningHorizontal/Vertical` | int | 픽셀 합성 (대역폭·fps 절약) |

현장 카메라는 **4K 풀 해상도** 기준으로 healthcheck PASS (~23fps). ROI/binning 변경 시 대역폭·fps 재검증 필요.

#### Gamma

| 경로 | Feature / API | 비고 |
|------|---------------|------|
| 카메라 내부 | `GammaEnable`, `GammaMode`, `Gamma` | **권장** — raw/Bayer 파이프라인과 일치 |
| 호스트 후처리 | `GammaParam`, `DxGetGammatLut`, `image_improvement()` | RGB 변환 **이후** 품질 보정용 (`GxSingleCamColor.py`) |

녹화·detection 파이프라인은 Bayer raw 유지 → **카메라 `Gamma` 설정이 기본**.

#### Pixel format

| Feature | 비고 |
|---------|------|
| `PixelFormat` | 운영: `BayerRG8` (`.env` `PIXEL_FORMAT`) |

### 3.3 cam_acq 앱 현황 (Parameter Control)

| 항목 | 앱 동작 | 비고 |
|------|---------|------|
| ExposureTime, ExposureAuto, Gain, GainAuto, AcquisitionFrameRate, GammaMode, Gamma | **런타임 PATCH** | 사용자 PATCH 시에만 grab 스레드가 1회 반영 (`RuntimeParamStore`) |
| Width / Height | **조회만** | `grab.py` `_read_geometry()`; 실패 시 `.env` fallback |
| PixelFormat | `.env` | 오픈 시 적용은 추후 |

**API** (grab와 **동일 프로세스**에서 `--with-monitoring` 시):

```
GET   /api/cameras/{camera_index}/params
PATCH /api/cameras/{camera_index}/params
```

예: `cam-acq-yolo-live --with-monitoring` → UI/curl **PATCH** → grab 스레드가 신호 수신 시 **한 번** GenICam `set()` (프레임마다 적용 아님).  
Monitoring UI 설정 창은 Phase 5 (`10_monitoring_design.md` §3.1).  
별도 프로세스 검증: `cam-acq-params` CLI → 동작 중인 grab의 HTTP API (`§3.1`).  
단독 `cam-acq-monitoring`은 grab 미연결 시 `503 parameter control not enabled`.

GigE reconnect 후 `feature_load`로 초기화되면 store가 **desired 값을 재적용** (`requeue`).

### 3.4 후처리 파라미터 (카메라 아님)

| 파라미터 | 처리 위치 |
|----------|-----------|
| Resize (detection 썸네일) | 호스트/GPU — `.env` `RESIZE_WIDTH/HEIGHT` |
| Demosaic (녹화) | GPU (encode 직전) |
| Encode bitrate / codec | NVENC — `.env` `ENCODING_*` |

## 4. 해상도 조회

SDK에서 조회 가능. `.env` fallback은 조회 실패 시에만 사용.

```python
# Python gxipy
width  = cam.Width.get()           # 현재 ROI width
height = cam.Height.get()
# 프레임: raw_image.get_width(), raw_image.get_height()
# 센서 최대: cam.SensorWidth.get(), cam.SensorHeight.get()
```

`.env` fallback:

```bash
CAMERA_WIDTH=0    # 0 = SDK auto
CAMERA_HEIGHT=0
```

## 5. 시간 동기화 (host clock)

### SDK feature (문서·API 기준)

**PTP (미지원 확인됨 — 현장 test 2대)**

- Feature: `PtpEnable`, `PtpStatus`, `PtpOffsetFromMaster`, `PtpDataSetLatch`
- Python: `FeatureControl` 문자열 API (`cam.get_remote_device_feature_control()`)
- 샘플: `c/sample/CSharp/GxActionCommand/` (PTP + ActionCommand)

**Timestamp (GenICam 카운터)**

| Feature | 타입 | 역할 |
|---------|------|------|
| `TimestampTickFrequency` / `GevTimestampTickFrequency` | int (read) | tick Hz → µs 변환 |
| `TimestampLatch` | command | 현재 카운터 latch |
| `TimestampLatchValue` | int (read) | latch 값 |
| `TimestampReset` | command | **카운터 0 리셋** (wall clock 설정 아님) |
| `ChunkTimestamp` | int (read) | Chunk mode 시 FrameStart 시각 |

- Python (Device shortcut): `cam.TimestampReset.send_command()` 등 (`gxipy/Device.py`)
- CLI: `cam_acq.tools.timestamp_test` (`--reset`로 실제 리셋 + before/after 기록)
- Phase 2 `TimeSyncManager`: 세션 시작 시 `reset_all_timestamps()` + host `monotonic` 앵커

### 현장 확인 사항 (2026-06-29, test 2대)

| 항목 | 결과 |
|------|------|
| Galaxy Viewer | PTP 관련 UI **없음** |
| `ptp_test` | `ptp_hw_supported: false` (2대), `recommendation: host_clock_sync` |
| `grab_healthcheck` 60s | **PASS** — cam0 22.7fps, cam1 22.6fps, drop 0 |
| `timestamp_test` | Phase 2에서 `--reset` 실행 후 결과 기록 예정 |

### 토폴로지 (4-port 직결)

카메라가 포트별 L2 분리 → **카메라 간 PTP sync 불가**.  
**운영 동기화:** host monotonic (이벤트·녹화) + per-camera `frame.timestamp` (드랍·순서) + 세션 시작 `TimestampReset` (상대 0점). 상세: `09_network_topology.md`

## 6. GigE 복구

- `GXRegisterDeviceOfflineCallback` + MAC 기반 재오픈 + `GXFeatureLoad`
- 참고 샘플: `c/sample/GxGigeRecovery/GxGigeRecovery.cpp`

## 7. 대역폭 (2.5GigE, 4K@23fps)

```
3840 × 2160 × 1 byte × 23 fps ≈ 191 MB/s ≈ 1.53 Gbps / camera
```

Bayer8/Mono8 기준 2.5GigE 링크 내 수용 가능. 카메라별 독립 NIC(4ch) 사용 중.

## 8. 네트워크 튜닝

| 항목 | 상태 |
|------|------|
| Jumbo frame / MTU | 설정 완료 |
| Socket buffer | `c/SetSocketBufferSize.sh` — **적용 완료** |

```bash
sudo sdk/Galaxy_camera/c/SetSocketBufferSize.sh 20971520  # 20MB 예시
```

## 9. 카메라 naming (0-based)

`CAMERA0_IP`의 `0`은 **배열 인덱스**이며 IP 주소의 octet이 아니다.

```
CAMERA0_IP=192.168.1.101   # camera_index=0
CAMERA1_IP=192.168.1.102   # camera_index=1
CAMERA2_IP=192.168.1.103   # camera_index=2
```
