# cam_acq

3대 4K GigE 카메라 취득 · Human Detection · 이벤트 녹화 · 모니터링.

설계·설치: [docs/00_project_plan.md](docs/00_project_plan.md), [docs/04_install_guide.md](docs/04_install_guide.md)  
Monitoring (CPU/GPU/온도 UI): [docs/10_monitoring_design.md](docs/10_monitoring_design.md)  
현장 대기 작업: [docs/11_field_pending_work.md](docs/11_field_pending_work.md)

## 빠른 시작

```bash
cd ~/works/cam_acq
cp .env.example .env   # 카메라 IP 편집

uv sync
export LD_LIBRARY_PATH=$PWD/sdk/Galaxy_camera/c/lib/x86_64:$LD_LIBRARY_PATH

# PTP 미지원 확인 (부정 test)
uv run python -m cam_acq.tools.ptp_test --output ./healthcheck/ptp_report.json

# Timestamp / 세션 앵커
uv run python -m cam_acq.tools.timestamp_test --output ./healthcheck/timestamp_report.json
uv run python -m cam_acq.tools.timestamp_test --reset --output ./healthcheck/timestamp_reset.json

# 2대 60초 취득 검증
uv run python -m cam_acq.tools.grab_healthcheck --duration 60 --save-sample ./samples
```

## Phase 1 CLI

| 명령 | 설명 |
|------|------|
| `uv run python -m cam_acq.tools.ptp_test` | PTP 미지원 확인 (부정 test) |
| `uv run python -m cam_acq.tools.timestamp_test` | Timestamp feature probe / `--reset` |
| `uv run python -m cam_acq.tools.grab_healthcheck` | FPS/drop soak + JSON 리포트 |
| `uv run python -m cam_acq.tools.monitoring_server` | Phase 5 Dashboard (host metrics) |

상세: [docs/08_ssh_healthcheck_guide.md](docs/08_ssh_healthcheck_guide.md)

## systemd 서비스 등록 (운영 전환 시)

개발·검증은 위처럼 `uv run`으로 수동 실행한다. 운영 배포 시 전용 유저 `cam-acq` + systemd unit을 쓴다.

1. 저장소 권한: `sudo ./deploy/systemd/cam-acq-storage-setup.sh`
2. 환경: `sudo cp deploy/systemd/cam-acq.env.example /etc/cam-acq/cam-acq.env` 후 편집
3. 모니터링: `sudo cp deploy/systemd/cam-acq-monitoring.service /etc/systemd/system/` → `systemctl enable --now`

메인 acquisition 유닛은 Phase 4.3 통합 데몬 이후 등록한다.

**상세 절차:** [deploy/systemd/README.md](deploy/systemd/README.md)
