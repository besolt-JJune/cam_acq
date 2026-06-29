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
    "started_at_host_us": 0,
    "ended_at_host_us": 0
  },
  "buffer": {
    "pre_sec": 10,
    "post_sec": 10
  },
  "time_sync": {
    "strategy": "host_clock_sync",
    "session_host_t0_us": 0,
    "camera_ts0_us": 0,
    "tick_frequency_hz": 1000000000,
    "timestamp_reset_at_session": true
  },
  "split": {
    "interval_sec": 60,
    "segment_start_host_us": 0,
    "segment_end_host_us": 0
  },
  "storage": {
    "active_path": "/data/recordings",
    "is_fallback": false
  },
  "frames_file": "20250628_143022_cam0_seg00.frames.jsonl"
}
```

| 필드 | 설명 |
|------|------|
| `codec` | Phase 4 결정값 (`H264` 또는 `H265`) |
| `trigger.started_at_host_us` | 녹화 window 시작 (host monotonic, µs) |
| `time_sync` | 세션 앵커 (`TimestampReset` + `host_t0`). PTP 미사용 |
| `storage.active_path` | 실제 저장 경로 (`STORAGE_PATH` 또는 fallback `STORAGE_PATH_SUB`) |
| `storage.is_fallback` | `true`이면 `STORAGE_PATH_SUB` 사용 중 |
| `frames_file` | companion jsonl 경로 |

## 2. 프레임 메타 (`*.frames.jsonl`)

한 줄 = JSON 객체 1개 (NDJSON).

```json
{"frame_id":12345,"timestamp_us":371100,"host_recv_us":9876543210,"detections":[{"class":"person","confidence":0.91,"bbox_original":{"x1":100,"y1":200,"x2":300,"y2":600},"bbox_resized":{"x1":25,"y1":50,"x2":75,"y2":150}}],"recorded":true}
```

### 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `frame_id` | int | 카메라 frame ID |
| `timestamp_us` | int | 카메라 tick → µs (`TimestampTickFrequency`, 세션 기준 상대값) |
| `host_recv_us` | int | 호스트 수신 시각 (monotonic, µs) |
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
| P1 | TimeSync 세션 앵커 | `TimestampReset` + host monotonic (`architecture.md` §3.3) |
| P2 | 추가 센서/이벤트 필드 |

## 4. 테스트 (T6)

- mp4 재생 길이 ≈ (pre + event + post)
- `.json`의 `codec`, `resolution` 일치
- `.frames.jsonl` line 수 > 0, `recorded=true` 구간이 영상과 대응
- `bbox_original`이 4K 범위 내
