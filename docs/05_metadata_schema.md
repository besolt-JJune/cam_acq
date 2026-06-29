# 메타데이터 스키마

녹화 파일과 **동일 basename**, 확장자만 다르게 저장한다.

```
20250628_143022_cam0_seg00.mp4
20250628_143022_cam0_seg00.json           # session / segment 메타
20250628_143022_cam0_seg00.frames.jsonl   # 프레임별 (1 line = 1 frame)
```

## 1. Session 메타 (`*.json`)

```json
{
  "schema_version": "1.0",
  "recording_id": "550e8400-e29b-41d4-a716-446655440000",
  "segment_index": 0,
  "camera_index": 0,
  "video_file": "20250628_143022_cam0_seg00.mp4",
  "codec": "H265",
  "resolution": {"width": 3840, "height": 2160},
  "fps_nominal": 23.0,
  "trigger": {
    "type": "human_detection",
    "source": "auto",
    "manual": false,
    "started_at_ptp_us": 0,
    "ended_at_ptp_us": 0
  },
  "buffer": {
    "pre_sec": 10,
    "post_sec": 10
  },
  "ptp": {
    "enabled": true,
    "status": "Slave",
    "offset_from_master_us": 3
  },
  "split": {
    "interval_sec": 60,
    "segment_start_ptp_us": 0,
    "segment_end_ptp_us": 0
  },
  "frames_file": "20250628_143022_cam0_seg00.frames.jsonl"
}
```

| 필드 | 설명 |
|------|------|
| `codec` | Phase 4 결정값 (`H264` 또는 `H265`) |
| `trigger.source` | `auto` / `manual` |
| `frames_file` | companion jsonl 경로 |

## 2. 프레임 메타 (`*.frames.jsonl`)

한 줄 = JSON 객체 1개 (NDJSON).

```json
{"frame_id":12345,"timestamp_us":9876543210,"ptp_timestamp_us":9876543210,"detections":[{"class":"person","confidence":0.91,"bbox_original":{"x1":100,"y1":200,"x2":300,"y2":600},"bbox_resized":{"x1":25,"y1":50,"x2":75,"y2":150}}],"recorded":true}
```

### 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `frame_id` | int | 카메라 frame ID |
| `timestamp_us` | int | 카메라 내부 tick → Hz로 µs 변환 (`TimestampTickFrequency`) |
| `host_recv_us` | int | 호스트 수신 시각 (monotonic 기준, Phase 2) |
| `ptp_timestamp_us` | int | **미사용** (PTP 미지원) — 예약 필드 |
| `detections` | array | 검출 목록 |
| `detections[].class` | string | `"person"` |
| `detections[].confidence` | float | 0~1 |
| `detections[].bbox_resized` | object | RESIZE 좌표 |
| `detections[].bbox_original` | object | 4K 역변환 좌표 |
| `recorded` | bool | 해당 프레임이 mp4에 포함됐는지 |

### bbox 역변환

letterbox 사용 시 padding offset 보정 필요.

```
scale_x = camera_width  / RESIZE_WIDTH
scale_y = camera_height / RESIZE_HEIGHT
x1_orig = (x1_det - pad_x) * scale_x
```

## 3. 우선순위

| 우선순위 | 내용 |
|----------|------|
| P0 (테스트 T6) | session `.json` + `.frames.jsonl` 동기 저장 |
| P1 | PTP timestamp 통일 | **취소** — `TimestampReset` 세션 앵커 + host clock |
| P2 | 추가 센서/이벤트 필드 |

## 4. 테스트 (T6)

- mp4 재생 길이 ≈ (pre + event + post)
- `.json`의 `codec`, `resolution` 일치
- `.frames.jsonl` line 수 > 0, `recorded=true` 구간이 영상과 대응
- `bbox_original`이 4K 범위 내
