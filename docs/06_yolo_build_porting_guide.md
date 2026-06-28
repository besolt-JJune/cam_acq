# YOLO Build & DeepStream Porting Guide

모델: **YOLOv8m** (고정확도 우선, 4070 Ti Super 16GB에서 리소스 여유 허용)

## 1. 모델 선정

| 모델 | 정확도 | VRAM (640 FP16) | 용도 |
|------|--------|-----------------|------|
| yolov8n | 낮음 | ~1 GB | PoC만 |
| **yolov8m** | **중~상** | **~2–3 GB** | **권장** |
| yolov8l | 높음 | ~4–5 GB | v8m 부족 시 |
| yolov8x | 최고 | ~6–8 GB | 3ch+녹화 동시 부담 |

입력 크기: `DETECTION_INPUT_SIZE=640` (기본), 정확도 부족 시 `1280` (VRAM↑, engine 재빌드).

## 2. Build 절차

### 2.1 의존성

```bash
uv pip install ultralytics onnx onnxsim
```

### 2.2 ONNX export

```bash
yolo export model=yolov8m.pt format=onnx imgsz=640 simplify=True
```

person class만 필요하면 export 후 ONNX 수정 또는 post-filter (COCO class 0 = person).

### 2.3 TensorRT engine

**반드시 RTX 4070 Ti Super (sm_89)에서 빌드.**

```bash
trtexec --onnx=yolov8m.onnx \
  --saveEngine=models/yolov8m_person.engine \
  --fp16 \
  --minShapes=images:1x3x640x640 \
  --optShapes=images:1x3x640x640 \
  --maxShapes=images:1x3x640x640
```

DeepStream 9.0 + TensorRT 10.14.x 환경에서 실행.

### 2.4 라벨 파일

`models/labels.txt` — COCO 80 class (person = index 0).

## 3. DeepStream nvinfer 설정

`configs/nvinfer/config_infer_primary_yolo.txt` 예시:

```ini
[property]
gpu-id=0
net-scale-factor=0.003921569790691137
model-color-format=0
onnx-file=../../models/yolov8m.onnx
model-engine-file=../../models/yolov8m_person.engine
labelfile-path=../../models/labels.txt
batch-size=3
network-mode=2
num-detected-classes=80
interval=0
gie-unique-id=1
process-mode=1
network-type=0
cluster-mode=2
maintain-aspect-ratio=1
parse-bbox-func-name=NvDsInferParseYolo
custom-lib-path=/opt/nvidia/deepstream/deepstream/lib/libnvdsinfer_custom_impl_Yolo.so

[class-attrs-all]
pre-cluster-threshold=0.5
```

## 4. Porting 체크리스트

| # | 항목 | 확인 |
|---|------|------|
| 1 | `libnvdsinfer_custom_impl_Yolo.so` DS 9.0 경로 | `/opt/nvidia/deepstream/deepstream/lib/` |
| 2 | `batch-size` = `NUM_CAMERAS` (3) | nvstreammux batch |
| 3 | `maintain-aspect-ratio=1` | bbox 역변환과 일치 |
| 4 | person만 사용 | class 0 filter |
| 5 | input size 변경 | engine **재빌드** |
| 6 | GPU 변경 | engine **재빌드** |
| 7 | Bayer 입력 | upstream `nvvideoconvert` → RGB/NV12 |
| 8 | `.env` `DETECTION_MODEL_PATH` | engine 경로 |

## 5. bbox 역변환

```
scale_x = CAMERA_WIDTH  / RESIZE_WIDTH
scale_y = CAMERA_HEIGHT / RESIZE_HEIGHT
```

letterbox padding (`pad_x`, `pad_y`) 보정 후 `bbox_original` 산출.  
메타 저장: `05_metadata_schema.md`

## 6. 검증

```bash
deepstream-app -c configs/deepstream_app_yolo_3cam.txt
```

- overlay 영상에서 person bbox 확인
- `DETECTION_CONFIDENCE` (기본 0.5) 조정
- trigger 이벤트 발행 확인

## 7. 관련 문서

- `04_install_guide.md` — TensorRT 환경
- `03_language_split.md` — GPU 파이프라인
- `00_project_plan.md` — Phase 3
