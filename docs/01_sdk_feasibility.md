# SDK 기능 검토 (Galaxy Camera SDK)

SDK 경로: `sdk/Galaxy_camera/c`, `sdk/Galaxy_camera/python`  
문서: `sdk/Galaxy_camera/c/doc/C_SDK_Programming_Reference_Manual.pdf`

## 1. 요구 기능 대응표

| 기능 | 구현 가능 | 구현 위치 | SDK 근거 |
|------|-----------|-----------|----------|
| 다중 카메라 스트리밍 | ✅ | SDK + 앱 | `GXUpdateAllDeviceList`, IP/MAC 오픈, `GXGetImage`/callback |
| 프레임 타임스탬프 | ✅ | 카메라 + SDK | `GX_FRAME_DATA.nTimestamp`, `TimestampLatch`/`TimestampLatchValue` |
| PTP 동기화 | ✅ (HW test 필요) | 카메라 GenICam | `PtpEnable`, `PtpStatus`, `PtpOffsetFromMaster` |
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

## 3. 카메라 파라미터: 내부 vs 후처리

| 파라미터 | 처리 위치 |
|----------|-----------|
| ExposureTime, Gain, FPS | 카메라 (GenICam) |
| Width, Height, ROI | 카메라 |
| Gamma | 카메라 (기본) |
| Resize (detection) | 호스트/GPU |
| Demosaic (녹화) | GPU (encode 직전) |

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

## 5. PTP / 시간 동기화

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
