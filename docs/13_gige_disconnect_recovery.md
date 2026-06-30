# GigE disconnect / reconnect 요구사항

카메라 Ethernet 분리·재연결 시 **대시보드(live)** 와 **이벤트/수동 녹화** 동작을 정의한다.  
구현 전 스펙; 현재 코드 상태와 갭을 §1에 명시.

관련: `camera/recovery.py`, `11_field_pending_work.md` §2.3, `00_project_plan.md` Phase 2.3·T9.

---

## 1. 현재 상태 (2026-06-30)

| 경로 | disconnect 감지 | 자동 재연결 | 비고 |
|------|------------------|------------|------|
| `grab_healthcheck --recovery` | ✅ offline callback | ✅ `grab_loop_with_recovery` | Phase 2.3 검증용 CLI |
| `cam-acq-yolo-live` / dashboard | ⚠️ FPS·`open_error`로 offline 표시 가능 | ❌ `recording/grab.run_camera_grab_loop` — recovery 미연동 | grab 스레드 종료 후 수동 재시작 필요 |
| `RecordingController` | ❌ | ❌ | disconnect 시 세그먼트 강제 종료·재개 없음 |

**갭:** `recovery.py`는 grab 전용으로 존재하나, **yolo-live + monitoring + recording** 통합 경로에 미연결.

---

## 2. 목표

1. **Dashboard (live):** disconnect 후 재연결 시 스트림·FPS·연결 상태가 **자동 복구**되어 운영 중 프로세스 재시작 없이 계속 모니터링 가능.
2. **Recording:** disconnect 시 해당 카메라 녹화 **일시 중단** 및 파일 **즉시 분리(close)**; 재연결 후 녹화 **재개** (새 파일). 시간 기반 split(`RECORDING_SPLIT_INTERVAL_SEC`)과 별도로 **disconnect 경계에서 반드시 파일 분리**.

---

## 3. Dashboard / live 파이프라인

### 3.1 적용 범위

- `cam-acq-yolo-live --with-monitoring` (운영: `scripts/yolo_live_dashboard.sh`)
- per-camera grab 스레드

### 3.2 동작

| 단계 | 요구 |
|------|------|
| disconnect 감지 | GigE offline callback (`register_device_offline_callback`) 또는 동등 수단. `GrabStats` / `RecoveryStats` 갱신. |
| UI 표시 | `cameras[].connection` → `offline`; `recovery_events` 증가; health `camera_offline:{idx}` (기존과 동일). |
| 재연결 | IP 기준 재오픈 → `feature_load`(백업) → `stream_on` → grab 루프 재개. |
| UI 복구 | `connection` → `online`; MJPEG `/api/stream/{id}` 재개; `fps_live` 복구. |
| 파라미터 | reconnect 후 `RuntimeParamStore.requeue` — desired GenICam 값 재적용 (기존 `param_store.py` 정책). |
| YOLO | 재연결 카메라만 detection/썸네일 공급 재개; 다른 채널 영향 최소화. |

### 3.3 비요구 (이번 스펙 밖)

- 프로세스 전체 재시작
- disconnect 중에도 마지막 프레임 freeze를 “online”으로 표시

### 3.4 검증 (구현 후)

yolo-live 실행 중 케이블 5~10초 분리 → 재연결:

```bash
# 분리 후
curl -s http://127.0.0.1:8080/api/cameras/0/stats | jq '{connection, recovery_events, open_error}'

# 재연결 후 (프로세스 재시작 없이)
# connection: online, fps_live ≥ 22, recovery_events ≥ 1
```

---

## 4. Recording (이벤트·수동)

### 4.1 적용 범위

- `RecordingController` + NVENC (`gst_encode.py`)
- auto trigger (`RecordingTrigger`) 및 manual REC (`POST /api/recording/trigger`)

### 4.2 disconnect 시

| 항목 | 요구 |
|------|------|
| 감지 시점 | GigE offline callback과 **동일 시점** (grab recovery와 공유). |
| 해당 카메라 | ring push 중단; 열려 있는 NVENC 세그먼트 **즉시 finalize** (EOS, mux close). |
| 파일 분리 | disconnect detect 시점이 **새 split 경계**. 기존 `segNN` 파일은 그 시점까지의 프레임만 포함. |
| 다른 카메라 | online인 채널은 녹화·인코딩 **계속** (2ch/3ch 독립). |
| 세션 상태 | 전체 trigger 세션이 열려 있어도, offline 카메라만 encode 중단; online 카메라는 유지. |

### 4.3 reconnect 시

| 항목 | 요구 |
|------|------|
| 녹화 재개 | **아직 종료되지 않은** recording 세션(event 침묵 tail 전, 또는 manual active)이면 해당 카메라 encode **재개**. |
| 새 파일 | 재개 시 **새 basename** / `segment_index` 증가 (disconnect split). disconnect 이전 프레임과 **동일 MP4에 이어 쓰지 않음**. |
| pre-buffer | 재연결 직후 pre-buffer는 **재연결 이후** ring에서만 공급 (disconnect 구간은 물리적으로 없음 — 기대 동작). |
| trigger 종료 | event 세션이 이미 `post_buffer` 완료·flush된 뒤 reconnect면 **새 person detect**로만 다음 세션 시작 (기존 trigger 규칙 유지). |

### 4.4 메타데이터 (`05_metadata_schema.md` 확장 예정)

disconnect로 닫힌 세그먼트는 session JSON에 split 사유 기록 (필드명은 구현 시 확정):

```json
"split": {
  "reason": "gige_disconnect",
  "at_host_us": 1234567890,
  "offline_event_index": 1
}
```

- 시간 기반 split: `"reason": "interval"` (기존 동작)
- manual stop: 기존 `trigger` 블록 유지

### 4.5 파일명

기존 규칙 유지 (`{ts}_cam{N}_seg{ii}.mp4`).  
disconnect split도 `seg` 인덱스 증가; 동일 세션 내 disconnect 전·후는 **서로 다른 seg 파일**.

예 (cam0, event 녹화 중 disconnect 1회):

```
20260630_120000_cam0_seg00.mp4   # disconnect 전
20260630_120000_cam0_seg00.json
20260630_120305_cam0_seg01.mp4   # reconnect 후 재개 (새 seg)
20260630_120305_cam0_seg01.json
```

타임스탬프 prefix 정책은 구현 시 `RecordingController` 기존 명명과 일치시킨다.

### 4.6 검증 (구현 후)

yolo-live + event recording, 녹화 활성 구간에서 cam0 케이블 분리 → 재연결:

1. disconnect 직후 cam0 `*_seg*.mp4` finalize (재생 가능, 크기 고정)
2. reconnect 후 cam0 **새** `*_seg*.mp4` 생성
3. cam1 파일은 분리 없이 연속 또는 interval split만 적용
4. session JSON `split.reason == gige_disconnect` (cam0 seg00)

---

## 5. 구현 시 통합 포인트 (참고만)

구현은 본 문서 범위 밖. 추후 작업 시 후보:

| 모듈 | 변경 방향 |
|------|----------|
| `recording/grab.py` 또는 yolo-live grab | `grab_loop_with_recovery` 재사용 또는 공통 래퍼 |
| `deepstream_yolo_live.py` | `LiveFeedStats`에 `RecoveryStats` 전달; `live_sync` hooks 반영 |
| `RecordingController` | per-camera offline → `finalize_segment(disconnect=True)`; online → resume if session active |
| `monitoring/payloads.py` | `recovery_events`, `reconnect_success` yolo-live 경로 노출 |

---

## 6. Phase / 테스트 매핑

| ID | 내용 |
|----|------|
| Phase 2.3 | grab recovery — **yolo-live 통합** 포함으로 범위 확장 |
| Phase 4.x | disconnect split + resume |
| Phase 5 | dashboard reconnect UX (§3) |
| Phase 6 **T9** | disconnect → offline → reconnect → online + recording 파일 분리 |

`grab_healthcheck --recovery`만으로는 T9 **PASS 불가** — 반드시 `cam-acq-yolo-live --with-monitoring` E2E 필요.

---

## 7. 관련 문서

| 문서 | 내용 |
|------|------|
| `architecture.md` | GigE reconnect, recording IPC |
| `10_monitoring_design.md` | connection / recovery API 필드 |
| `05_metadata_schema.md` | segment 메타, split reason |
| `11_field_pending_work.md` | 현장 케이블 test 절차 |
