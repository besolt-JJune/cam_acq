# Language 배치

## 1. 원칙

- **전체 실행/설정/테스트:** Python
- **고속 취득·저지연:** C (필요 시)
- **AI·영상 처리:** DeepStream (C/CUDA)
- **Python GIL:** inference/encode 파이프라인은 네이티브에 두고 Python은 제어만

## 2. 모듈별 배치

| 모듈 | 언어 | 비고 |
|------|------|------|
| 실행·설정·테스트 | Python | uv, `.env` |
| 카메라 grab (3×4K) | Python (Phase 1) → C (병목 시) | 2대 PoC 후 결정 |
| TimeSyncManager | Python | host monotonic + `TimestampReset` (`timestamp.py`) |
| GigE offline recovery | Python FeatureControl 또는 C | `GxGigeRecovery` 샘플 |
| Pre-buffer (Bayer 4K) | C 권장 / Python Phase 1 | RAM ring |
| Resize / debayer | **DeepStream GPU** | `nvvideoconvert` |
| Human Detection | DeepStream nvinfer | YOLOv8m TensorRT |
| Recording encode | GStreamer/DeepStream **NVENC** | HW only |
| Storage 관리 | Python | FIFO, 용량 |
| Web Monitoring | Python (FastAPI) | 로컬 Dashboard, host metrics UI |
| 로깅 | Python | 일별 파일 |

## 3. Demosaic 경로

| 용도 | 구현 |
|------|------|
| Pre-buffer | Bayer raw 저장 (demosaic 없음) |
| Detection | GPU resize stream (Bayer→YUV/RGB) |
| **녹화** | **Bayer → GPU debayer → NV12 → NVENC** |
| Phase 1 테스트 이미지 | SDK `convert("RGB")` (CPU) |

Bayer를 NVENC에 직접 넣지 않는다. 상세: `01_sdk_feasibility.md` §2.

## 4. GIL 고려

| 구성 | GIL |
|------|-----|
| Python 3×4K 프레임 루프 + numpy | 위험 |
| DeepStream subprocess, Python 제어 | 안전 |
| GStreamer `gi` / NVENC pipeline | 양호 |

## 5. Phase 1 전략

1. Python `gxipy`로 **2대** grab + healthcheck
2. 병목 확인 (FPS drop, CPU)
3. 문제 시 `native/cam_grab/` C 확장 도입
4. 3대 운영 전환 (Phase 2)

## 6. 코덱

NVENC HW encoding만 사용. H.265 vs H.264는 Phase 4 프로파일링 후 결정 (`00_project_plan.md` §4.1).
