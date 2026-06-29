# cam_acq

3대 4K GigE 카메라 취득 · Human Detection · 이벤트 녹화 · 모니터링.

설계·설치: [docs/00_project_plan.md](docs/00_project_plan.md), [docs/04_install_guide.md](docs/04_install_guide.md)  
Monitoring (CPU/GPU/온도 UI): [docs/10_monitoring_design.md](docs/10_monitoring_design.md)

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

상세: [docs/08_ssh_healthcheck_guide.md](docs/08_ssh_healthcheck_guide.md)
