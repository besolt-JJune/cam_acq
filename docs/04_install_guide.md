# 설치 가이드

Ubuntu 24.04 + RTX 4070 Ti Super + Galaxy GigE + DeepStream 9.0 (native)

> Ubuntu 24.04 사용 이유: 시스템 driver가 22.04에서 정상 동작하지 않음.

## 1. 사전 요구사항

| 항목 | 요구 |
|------|------|
| OS | Ubuntu 24.04 LTS |
| GPU | RTX 4070 Ti Super 16GB |
| RAM | 32GB |
| Driver | **590+** |
| CUDA | **13.1** |
| TensorRT | **10.14.x** |
| DeepStream | **9.0** (24.04 공식 지원) |
| GStreamer | 1.24.2 |

참고:
- [DeepStream 9.0 NGC](https://catalog.ngc.nvidia.com/orgs/nvidia/resources/deepstream/9.0)
- [Installation Guide](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Installation.html)

## 2. NVIDIA Driver

```bash
sudo apt update
sudo apt install -y linux-headers-$(uname -r)
sudo ubuntu-drivers install
# 또는: sudo apt install nvidia-driver-590
sudo reboot
nvidia-smi
```

## 3. CUDA 13.1

DeepStream 9.0 설치 문서의 권장 방식을 따른다.  
DS deb 패키지 또는 tar 설치 시 CUDA 의존성이 함께 안내된다.

## 4. DeepStream 9.0 (native)

```bash
# NGC에서 deepstream-9.0_9.0.0-1_amd64.deb 다운로드 후
sudo apt install ./deepstream-9.0_9.0.0-1_amd64.deb

deepstream-app --version

# 검증
deepstream-app -c /opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/source1_usb_dec_infer_resnet_int8.txt
```

Docker는 사용하지 않는다 (전용 시스템 native 구동).

## 5. Galaxy Camera SDK

### 5.1 라이브러리 경로

```bash
export LD_LIBRARY_PATH=/path/to/cam_acq/sdk/Galaxy_camera/c/lib:$LD_LIBRARY_PATH
```

영구 적용은 `~/.bashrc`(개발) 또는 systemd `Environment`/`cam-acq-run.sh`(운영)에 추가.

운영 배포(systemd): [deploy/systemd/README.md](../deploy/systemd/README.md)

### 5.2 Python gxipy

```bash
cd sdk/Galaxy_camera/python/api
uv pip install -e .   # 또는 python setup.py install
```

Galaxy Linux C SDK가 선행 설치되어 있어야 한다 (`python/README` 참고).

### 5.3 네트워크 튜닝

| 항목 | 상태 | 조치 |
|------|------|------|
| Jumbo / MTU | 완료 | — |
| Socket buffer | **적용 완료** | — |

```bash
sudo sdk/Galaxy_camera/c/SetSocketBufferSize.sh 20971520   # 20MB
```

## 6. Python 프로젝트 (uv)

```bash
cd /path/to/cam_acq
uv sync
cp .env.example .env   # 카메라 IP 편집

export LD_LIBRARY_PATH=$PWD/sdk/Galaxy_camera/c/lib/x86_64:$LD_LIBRARY_PATH

# 설정 로드 self-check (카메라 불필요)
uv run python tests/test_config.py

# PTP 미지원 확인 (부정 test, 기록용)
uv run python -m cam_acq.tools.ptp_test --output ./healthcheck/ptp_report.json

# Timestamp feature / 세션 앵커
uv run python -m cam_acq.tools.timestamp_test --output ./healthcheck/timestamp_report.json
uv run python -m cam_acq.tools.timestamp_test --reset --output ./healthcheck/timestamp_reset.json

# 2대 grab healthcheck
uv run python -m cam_acq.tools.grab_healthcheck --duration 60 --save-sample ./samples
```

또는 entry point:

```bash
uv run cam-acq-ptp-test
uv run cam-acq-timestamp-test
uv run cam-acq-timestamp-test --reset
uv run cam-acq-healthcheck --duration 60
```

## 7. TensorRT / YOLO engine

Phase 3에서 수행. 요약:

```bash
uv sync --extra build-yolo
uv run cam-acq-build-yolo --batch-size 3   # NUM_CAMERAS와 동일
```
```

상세: `06_yolo_build_porting_guide.md`

## 8. 설치 검증 체크리스트

- [ ] `nvidia-smi` — GPU 인식
- [ ] `deepstream-app --version`
- [ ] DeepStream sample 앱 실행
- [ ] `SetSocketBufferSize.sh` 적용
- [ ] gxipy import + 카메라 1대 open
- [ ] `uv run python tests/test_config.py`
- [ ] `uv run python -m cam_acq.tools.ptp_test` — `host_clock_sync` 확인
- [ ] `uv run python -m cam_acq.tools.timestamp_test --reset`
- [ ] `uv run python -m cam_acq.tools.grab_healthcheck --duration 60` PASS

## 9. 관련 문서

- `09_network_topology.md` — netplan, 시간 동기화 (host clock)
- `08_ssh_healthcheck_guide.md`
- `06_yolo_build_porting_guide.md`
- `00_project_plan.md`
- `../deploy/systemd/README.md` — systemd 서비스 등록 (운영 전환 시)
