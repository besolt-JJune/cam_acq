# 네트워크 토폴로지

4-port NIC, switch 없이 포트별 카메라 직결 구성.

## 1. 물리 구성

```
[Host 4-port NIC]
  enp22s0  10.10.1.0/24  ←──직결──→  Camera0
  enp23s0  10.10.2.0/24  ←──직결──→  (예비)
  enp25s0  10.10.3.0/24  ←──직결──→  (예비)
  enp26s0  10.10.4.0/24  ←──직결──→  Camera1

Test env: Camera0 → enp22s0, Camera1 → enp26s0
```

- 포트마다 **다른 /24 대역** (권장). 같은 대역으로 맞춰도 L2가 이어지지 않아 **카메라 간 PTP는 불가**.
- 앱은 `CAMERAx_IP`에 실제 IP만 지정. 대역이 달라도 OK.

## 2. netplan 예시 (routes 주석)

point-to-point 직결에서는 `connected route`로 충분하다.  
`via: 10.10.x.1` gateway는 직결 세그먼트에 장비가 없으면 **불필요**하므로 주석 처리.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp22s0:
      dhcp4: false
      addresses:
        - 10.10.1.2/24
      mtu: 9000
      # routes:
      #   - to: 10.10.1.0/24
      #     via: 10.10.1.1

    enp23s0:
      dhcp4: false
      addresses:
        - 10.10.2.2/24
      mtu: 9000
      # routes:
      #   - to: 10.10.2.0/24
      #     via: 10.10.2.1

    enp25s0:
      dhcp4: false
      addresses:
        - 10.10.3.2/24
      mtu: 9000
      # routes:
      #   - to: 10.10.3.0/24
      #     via: 10.10.3.1

    enp26s0:
      dhcp4: false
      addresses:
        - 10.10.4.2/24
      mtu: 9000
      # routes:
      #   - to: 10.10.4.0/24
      #     via: 10.10.4.1
```

적용:

```bash
sudo netplan apply
```

## 3. 연결 확인

```bash
ip -br addr show enp22s0 enp26s0
ip route get 10.10.1.101    # dev enp22s0 기대
ip route get 10.10.4.101    # dev enp26s0 기대
ping -c 3 -I enp22s0 10.10.1.101
ping -c 3 -I enp26s0 10.10.4.101
```

## 4. `.env` 예시 (test 2대)

```bash
NUM_CAMERAS=2
CAMERA0_IP=10.10.1.101
CAMERA1_IP=10.10.4.101

CAMERA0_INTERFACE=enp22s0
CAMERA1_INTERFACE=enp26s0
```

`camera_index`는 0부터. IP octet과 무관.

## 5. 시간 동기화 (PTP / Timestamp)

| 항목 | 현황 |
|------|------|
| Galaxy Viewer | PTP 관련 UI **미표시** |
| PTP GenICam | **HW 미지원** (test 2대, `ptp_hw_supported: false`) |
| SDK Timestamp API | `TimestampReset`, `TimestampLatch`, `TimestampLatchValue` |
| 확인 CLI | `ptp_test`, `timestamp_test` (`--reset`) |

### 5.1 이 토폴로지에서 PTP

카메라가 **서로 다른 포트(L2 분리)** 에 연결되어 **카메라 간 PTP sync는 불가**.  
현장 test: PTP feature **미구현** → PTP 경로 폐기.

### 5.2 확인 방법

**PTP** — gxipy `FeatureControl` (`ptp_test`):

1. `GevSupportedOptionSelector=Ptp` → `GevSupportedOption` → **false** (현장)
2. `PtpEnable`/`PtpStatus` — **미구현** (현장)

**Timestamp** — `timestamp_test` CLI:

1. `TimestampReset` / `TimestampLatch` / `TimestampLatchValue` implemented 여부
2. `--reset`: latch → `TimestampReset` → latch (before/after JSON 기록)
3. 세션 시작 시 3대 순차 reset + host `monotonic` 앵커 (Phase 2 TimeSyncManager)

### 5.3 운영 시 TimeSync (확정)

| 방식 | 사용 |
|------|------|
| 카메라 간 PTP | ❌ (토폴로지 + HW 미지원) |
| 호스트 monotonic clock | ✅ 이벤트·녹화 경계 |
| 카메라 `frame.timestamp` | ✅ 채널 내 순서·드랍 |
| `TimestampReset` (세션 시작) | ✅ 채널별 상대 0점 (`timestamp_test --reset`) |
| NTP (호스트) | 보조 — 로그 wall clock (필요 시 chrony) |

## 6. 관련 문서

- `01_sdk_feasibility.md` — PTP feature, Demosaic
- `08_ssh_healthcheck_guide.md` — 취득 안정성 확인
- `00_project_plan.md` — Phase 1.4 PTP test
