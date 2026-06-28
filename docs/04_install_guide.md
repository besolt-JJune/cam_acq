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

영구 적용은 `~/.bashrc` 또는 systemd unit에 추가.

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
| Socket buffer | **미적용** | 아래 실행 |

```bash
sudo sdk/Galaxy_camera/c/SetSocketBufferSize.sh 20971520   # 20MB
```

## 6. Python 프로젝트 (uv)

```bash
cd /path/to/cam_acq
uv venv
uv sync
cp .env.example .env
# .env 편집
```

## 7. TensorRT / YOLO engine

Phase 3에서 수행. 요약:

```bash
uv pip install ultralytics onnx onnxsim
yolo export model=yolov8m.pt format=onnx imgsz=640 simplify=True
trtexec --onnx=yolov8m.onnx --saveEngine=models/yolov8m_person.engine --fp16
```

상세: `06_yolo_build_porting_guide.md`

## 8. 설치 검증 체크리스트

- [ ] `nvidia-smi` — GPU 인식
- [ ] `deepstream-app --version`
- [ ] DeepStream sample 앱 실행
- [ ] `SetSocketBufferSize.sh` 적용
- [ ] gxipy import + 카메라 1대 open
- [ ] `grab_healthcheck --duration 60` PASS

## 9. 관련 문서

- `08_ssh_healthcheck_guide.md`
- `06_yolo_build_porting_guide.md`
- `00_project_plan.md`
