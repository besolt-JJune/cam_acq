# YOLO Build & DeepStream Porting Guide

모델: **YOLOv8m** (고정확도 우선, 4070 Ti Super 16GB에서 리소스 여유 허용)

## 1. 모델 선정


| 모델          | 정확도     | VRAM (640 FP16) | 용도           |
| ----------- | ------- | --------------- | ------------ |
| yolov8n     | 낮음      | ~1 GB           | PoC만         |
| **yolov8m** | **중~상** | **~2–3 GB**     | **권장**       |
| yolov8l     | 높음      | ~4–5 GB         | v8m 부족 시     |
| yolov8x     | 최고      | ~6–8 GB         | 3ch+녹화 동시 부담 |


입력 크기: `DETECTION_INPUT_SIZE=640` (기본), 정확도 부족 시 `1280` (VRAM↑, engine 재빌드).

## 2. Build 절차

### 2.1 의존성

```bash
uv pip install ultralytics onnx onnxsim
```

### 2.2 ONNX export

```bash
yolo export model=yolov8m.pt format=onnx imgsz=640 simplify=True
# → yolov8m.onnx (COCO 80 class head 그대로)
```

person-only 상세 설정은 **§3** 참고. DeepStream-Yolo parser용 export가 필요하면:

```bash
cp third_party/DeepStream-Yolo/utils/export_yoloV8.py .
python3 export_yoloV8.py -w yolov8m.pt --simplify
```



### 2.3 TensorRT engine

**반드시 RTX 4070 Ti Super (sm_89)에서 빌드.** DS 9.0 + CUDA 13.1 호스트는 `export CUDA_VER=13.1`.

```bash
# 1) DeepStream-Yolo parser
./scripts/setup_deepstream_yolo.sh

# 2) ONNX export (batch = NUM_CAMERAS)
uv run cam-acq-build-yolo --env-file .env --variant person

# 3) 산출물 (person-only 배포, 80-class head + runtime filter)
#    models/yolov8m_person.onnx
#    models/yolov8m_person_b{N}_gpu0_fp16.engine
# coco 전체 비교용: --variant coco → yolov8m.onnx / yolov8m_b{N}_gpu0_fp16.engine
```

DeepStream 9.0 + TensorRT 10.14.x 환경에서 실행.

### 2.4 라벨 파일

`models/labels.txt` — COCO 80 class, **1번째 줄(index 0) = person**.

## 3. person class만 추출 — 설정 항목

COCO **class 0 = person**. cam_acq는 ONNX/engine을 **80 class 그대로** 두고, 아래 항목에서 **런타임·설정으로 person만 취한다**.


| #    | 구분              | 파일 / 위치                                         | person-only에서 할 일                      |
| ---- | --------------- | ----------------------------------------------- | -------------------------------------- |
| 3.1  | ONNX export     | §2.2                                            | 80 class 유지 (head 수정 **금지**)           |
| 3.2  | export 검증       | CLI                                             | `classes=0` predict                    |
| 3.3  | TensorRT engine | `trtexec` / `.env`                              | engine 경로·파일명                          |
| 3.4  | 라벨              | `models/labels.txt`                             | index 0 = person, 80줄 유지               |
| 3.5  | 환경 변수           | `.env`                                          | confidence·model path                  |
| 3.6  | nvinfer         | `configs/nvinfer/config_infer_primary_yolo.txt` | `num-detected-classes=80`, class-attrs |
| 3.7  | Python 필터       | `src/cam_acq/detection/bbox.py`                 | `PERSON_CLASS_ID=0`                    |
| 3.8  | 이벤트·트리거         | `src/cam_acq/detection/events.py`               | `filter_person_detections`             |
| 3.9  | 메타 JSON         | `docs/05_metadata_schema.md`                    | `detections[].class = "person"`        |
| 3.10 | 검증              | §7, `tests/test_detection.py`                   | person bbox·필터 테스트                     |


---



### 3.1 ONNX export

**변경 없음.** COCO pretrained `yolov8m.pt`를 80 class head 그대로 export.

```bash
yolo export model=yolov8m.pt format=onnx imgsz=640 simplify=True
```

- ONNX class head를 1 class로 자르거나 `num-detected-classes=1`로 맞추려 하지 **않는다** (DeepStream YOLO parser shape 불일치).



### 3.2 export 검증 (Ultralytics predict)

export 품질·person 검출 확인용. **필터는** `classes=0` **CLI 옵션** (ONNX 파일 자체는 변경하지 않음).

```bash
wget -O bus.jpg https://ultralytics.com/images/bus.jpg
yolo predict model=yolov8m.pt source=bus.jpg classes=0 conf=0.5 save=True
# 결과: runs/detect/predict*/bus.jpg — person bbox만 표시
```

로컬 사진·웹캠: `source=/path/to/photo.jpg` 또는 `source=0`

### 3.3 TensorRT engine

engine **내부는 80 class**. 파일명 `yolov8m_person.engine`은 **person 용도 표기**일 뿐.

```bash
# trtexec: /usr/src/tensorrt/bin/trtexec (libnvinfer-bin, PATH 미등록)
# ONNX 입력 텐서명 = input (images 아님). export_yoloV8.py static batch면 shape 옵션 생략.
/usr/src/tensorrt/bin/trtexec --onnx=models/yolov8m.onnx \
  --saveEngine=models/yolov8m_person.engine \
  --fp16
```

권장: DeepStream-Yolo 호환 ONNX + engine 일괄 빌드

```bash
./scripts/setup_deepstream_yolo.sh
uv run cam-acq-build-yolo --env-file .env --variant person
# batch = NUM_CAMERAS (현재 2 → yolov8m_person_b2_gpu0_fp16.engine)
```

`.env` / `src/cam_acq/config.py` 기본값과 맞출 것:

```ini
DETECTION_MODEL_PATH=models/yolov8m_person_b2_gpu0_fp16.engine
DETECTION_ONNX_PATH=models/yolov8m_person.onnx
```



### 3.4 라벨 파일 (`models/labels.txt`)

DeepStream nvinfer가 class id → 이름 매핑에 사용. **80줄 COCO 순서 유지**, 첫 줄이 person.

```
person      ← class id 0
bicycle
car
...
```

- 1줄만(`person`) 두는 방식은 DeepStream-Yolo 예제용. cam_acq는 **80줄 유지** (다른 class id가 올라와도 이름·디버그 정확).
- overlay·메타에 person만 남기는 건 **3.7·3.8 Python 필터**에서 처리.



### 3.5 환경 변수 (`.env`)

person confidence threshold. Python 필터(`filter_person_detections`)와 동일 값 사용.

```ini
DETECTION_CONFIDENCE=0.5
DETECTION_INPUT_SIZE=640
DETECTION_MODEL_PATH=models/yolov8m_person.engine
DETECTION_ONNX_PATH=models/yolov8m.onnx
```

- threshold 올리면 person만 더 보수적으로 통과 (car 등 다른 class는 애초에 3.7에서 제거).



### 3.6 DeepStream nvinfer (`configs/nvinfer/config_infer_primary_yolo.txt`)

person-only overlay·메타: nvinfer에서 **class 0만 통과**.

```ini
[property]
num-detected-classes=80          # 1로 바꾸지 않음
filter-out-class-ids=1;2;...;79  # COCO 1..79 제거 (0=person만 유지)
labelfile-path=../../models/labels.txt
model-engine-file=../../models/yolov8m_person_b2_gpu0_fp16.engine
```

```ini
[class-attrs-all]
pre-cluster-threshold=0.99       # non-person 사전 차단 (filter-out과 이중)

[class-attrs-0]
pre-cluster-threshold=0.5        # person — .env DETECTION_CONFIDENCE와 맞추기
```

Python 경로(3.7)도 동일하게 person만 통과. overlay 재생성:

```bash
deepstream-app -c configs/deepstream/deepstream_app_yolo_file_2ch_overlay.txt
```

### 3.7 Python 필터 (`src/cam_acq/detection/bbox.py`)

nvinfer raw meta → person만 통과.

```python
PERSON_CLASS_ID = 0
PERSON_CLASS_NAME = "person"

def filter_person_detections(detections, *, confidence_threshold, class_id=PERSON_CLASS_ID):
    return [
        d for d in detections
        if d.class_id == class_id and d.confidence >= confidence_threshold
    ]
```

호출 예:

```python
from cam_acq.detection.bbox import RawDetection, BBox, filter_person_detections

raw = [
    RawDetection(0, "person", 0.91, BBox(100, 50, 150, 200)),
    RawDetection(2, "car", 0.88, BBox(10, 10, 200, 200)),  # 제외
]
persons = filter_person_detections(raw, confidence_threshold=0.5)
```



### 3.8 이벤트·녹화 트리거 (`src/cam_acq/detection/events.py`)

프레임 이벤트 빌드 시 3.7 필터 적용. 메타·트리거 모두 person만 포함.

```python
# build_detection_event() 내부
persons = filter_person_detections(raw, confidence_threshold=confidence_threshold)
```

- `DetectionFrameEvent.has_person` — person 1건 이상이면 `True`
- `RecordingTrigger` — `has_person`일 때만 녹화 연장

`.env` `DETECTION_CONFIDENCE` → `build_detection_event(..., confidence_threshold=...)`로 전달.

### 3.9 메타데이터 JSON (`docs/05_metadata_schema.md`)

person 필터 **이후** 저장되므로 `detections[]`에는 person만 등장.

```json
"detections": [
  {"class": "person", "confidence": 0.91, "bbox_original": {...}, "bbox_resized": {...}}
]
```

다른 COCO class 문자열(`"car"` 등)이 보이면 3.7 필터가 적용되지 않은 경로를 의심.

### 3.10 검증

**Ultralytics (export 직후):** §3.2 `classes=0` predict

**DeepStream file 소스 (카메라 불필요):**

```bash
deepstream-app -c configs/deepstream/deepstream_app_yolo_file_2ch_overlay.txt
```

**Live GigE 2ch (카메라 필요):**

```bash
export LD_LIBRARY_PATH=$PWD/sdk/Galaxy_camera/c/lib/x86_64:$LD_LIBRARY_PATH
uv run cam-acq-yolo-live --duration 30 --output ./healthcheck/yolo_live.json
# overlay MP4: samples/deepstream_yolo_overlay_live_2ch.mp4
```

- overlay에서 person bbox만 기대 (`filter-out-class-ids` §3.6)
- `frames_pushed` / `fps_pushed_avg` ≥ 18 (23fps 목표의 ~80%)

**단위 테스트:**

```bash
uv run python tests/test_detection.py
# test_filter_person, test_build_detection_event — non-person 제거 확인
```



### 3.11 하지 말 것


| 설정                       | 이유                                               |
| ------------------------ | ------------------------------------------------ |
| `num-detected-classes=1` | YOLOv8m 출력 shape ≠ parser 기대                     |
| ONNX class head 잘라내기     | engine/parser 재호환 필요, 이득 없음                      |
| person-only ONNX 재학습     | cam_acq 범위 밖 (pretrained COCO + post-filter로 충분) |




## 4. DeepStream nvinfer 설정

`configs/nvinfer/config_infer_primary_yolo.txt` 예시:

```ini
[property]
gpu-id=0
net-scale-factor=0.003921569790691137
model-color-format=0
onnx-file=../../models/yolov8m_person.onnx
model-engine-file=../../models/yolov8m_person_b2_gpu0_fp16.engine
labelfile-path=../../models/labels.txt
batch-size=2
network-mode=2
num-detected-classes=80
interval=0
gie-unique-id=1
process-mode=1
network-type=0
cluster-mode=2
maintain-aspect-ratio=1
parse-bbox-func-name=NvDsInferParseYolo
custom-lib-path=../../third_party/DeepStream-Yolo/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so

[class-attrs-all]
pre-cluster-threshold=0.5
```

person-only class-attrs·필터 상세: **§3.6, §3.7**.

## 5. Porting 체크리스트


| #   | 항목                                           | 확인                                                                                                                                                                                                                 |
| --- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `libnvdsinfer_custom_impl_Yolo.so` DS 9.0 경로 | /usr/src/tensorrt/bin/trtexec --onnx=models/yolov8m.onnx \ --saveEngine=models/yolov8m_person.engine \--fp16 \--minShapes=images:1x3x640x640 \--optShapes=images:1x3x640x640 \--maxShapes=images:1x3x640x640 |
| 2   | `batch-size` = `NUM_CAMERAS` (3)             | nvstreammux batch                                                                                                                                                                                                  |
| 3   | `maintain-aspect-ratio=1`                    | bbox 역변환과 일치                                                                                                                                                                                                       |
| 4   | person-only                                  | **§3 전 항목**                                                                                                                                                                                                        |
| 5   | input size 변경                                | engine **재빌드**                                                                                                                                                                                                     |
| 6   | GPU 변경                                       | engine **재빌드**                                                                                                                                                                                                     |
| 7   | Bayer 입력                                     | upstream `nvvideoconvert` → RGB/NV12                                                                                                                                                                               |
| 8   | `.env` `DETECTION_MODEL_PATH`                | engine 경로                                                                                                                                                                                                          |




## 6. bbox 역변환

```
scale_x = CAMERA_WIDTH  / RESIZE_WIDTH
scale_y = CAMERA_HEIGHT / RESIZE_HEIGHT
```

letterbox padding (`pad_x`, `pad_y`) 보정 후 `bbox_original` 산출.  
메타 저장: `05_metadata_schema.md`

## 7. 검증

**File 소스 (카메라 불필요):**

```bash
deepstream-app -c configs/deepstream/deepstream_app_yolo_file_2ch_overlay.txt
```

**Live 2ch (카메라 + pyds):**

```bash
export LD_LIBRARY_PATH=$PWD/sdk/Galaxy_camera/c/lib/x86_64:$LD_LIBRARY_PATH
uv run cam-acq-yolo-live --duration 30 --output ./healthcheck/yolo_live.json
jq '.detection' ./healthcheck/yolo_live.json
```

현장 검증 체크리스트: `11_field_pending_work.md` §6

- overlay person bbox — §6.2
- `detection.trigger_events` — §6.3 (`RecordingTrigger` via nvinfer probe)
- `DETECTION_CONFIDENCE` — §3.5
- person-only — §3.10 (`tests/test_detection.py`)



## 8. 관련 문서

- `04_install_guide.md` — TensorRT 환경
- `03_language_split.md` — GPU 파이프라인
- `05_metadata_schema.md` — detection JSON
- `00_project_plan.md` — Phase 3

