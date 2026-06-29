# systemd 서비스 등록 (운영 배포용)

현재 개발·검증은 `uv run`으로 수동 실행한다. **운영 전환 시** 아래 순서로 등록한다.

관련 경로:

| 경로 | 용도 |
|------|------|
| `/mnt/data_pool/recordings` | primary 녹화 (`STORAGE_PATH`, MergerFS) |
| `/var/lib/cam-acq/` | 로그·healthcheck·fallback 녹화 |
| `/etc/cam-acq/cam-acq.env` | systemd 환경변수 |
| `cam-acq` (시스템 유저) | 서비스 실행 주체 |

---

## 1. 사전 조건

- [docs/04_install_guide.md](../../docs/04_install_guide.md) 설치 완료 (`uv sync`, GPU, DeepStream, 카메라 grab PASS)
- MergerFS 마운트: [docs/SSD_automount_guide.md](../../docs/SSD_automount_guide.md)
- 프로젝트 `.env`에 카메라 IP 등 설정 완료

---

## 2. 서비스 유저 + 저장소 권한

primary(`/mnt/data_pool/recordings`)는 **root 소유 755**이면 `cam-acq` 유저가 쓸 수 없어 `STORAGE_PATH_SUB`로 fallback 한다.

`cam-acq-storage-setup.sh`는 **서비스 유저 + SFTP/개발 유저 공유 그룹**(`cam-acq`)으로 설정한다:

- `/mnt/data_pool` — `root:root` `755` 유지 (OpenSSH SFTP chroot 호환)
- `/mnt/data_pool/recordings` — `cam-acq:cam-acq` `2770` (setgid, 그룹 공유)
- `besolt` 등 SFTP 사용자 → `cam-acq` 그룹 추가

```bash
cd /path/to/cam_acq
# 다른 SFTP 계정이 있으면: sudo STORAGE_GROUP_USERS="besolt otheruser" ./deploy/systemd/cam-acq-storage-setup.sh
sudo ./deploy/systemd/cam-acq-storage-setup.sh
```

**MergerFS 주의:** `/mnt/data_pool`은 mergerfs입니다. `usermod -aG cam-acq` 후에도 **보조 그룹이 mergerfs 캐시에 안 잡히면** `id`에 `cam-acq`가 보여도 `touch`가 실패할 수 있습니다. SFTP(새 세션)와 달리 로컬 셸은 **primary gid가 `besolt`(1000)** 인 채로 mergerfs에 접근합니다.

**해결 (호스트에서 sudo):**

```bash
cd ~/works/cam_acq
sudo ./deploy/systemd/cam-acq-storage-setup.sh   # ACL + mergerfs remount 포함
touch /mnt/data_pool/recordings/.test && rm /mnt/data_pool/recordings/.test
```

수동:

```bash
sudo setfacl -m u:besolt:rwx /mnt/data_pool/recordings /mnt/ssd1/recordings /mnt/ssd2/recordings
sudo setfacl -d -m u:besolt:rwx /mnt/data_pool/recordings /mnt/ssd1/recordings /mnt/ssd2/recordings
sudo mount -o remount /mnt/data_pool
```

임시: `sg cam-acq -c 'uv run cam-acq-record-test ...'` (primary gid를 cam-acq로 바꿔서 동작 확인됨)

**그룹 확인:**

```bash
id    # groups에 cam-acq(983) — 필요조건이지만 mergerfs에서는 ACL/remount도 필요할 수 있음
```

---

## 3. 환경 파일

```bash
sudo mkdir -p /etc/cam-acq
sudo cp deploy/systemd/cam-acq.env.example /etc/cam-acq/cam-acq.env
sudo nano /etc/cam-acq/cam-acq.env
```

`cam-acq.env.example`에서 반드시 맞출 항목:

| 변수 | 설명 |
|------|------|
| `CAM_ACQ_ROOT` | 프로젝트 루트 (venv·모델·configs 경로) |
| `STORAGE_PATH` | primary 녹화 경로 |
| `STORAGE_PATH_SUB` | fallback (`/var/lib/cam-acq/recordings` 권장) |
| `LOG_PATH` | 로그 디렉터리 |
| `HEALTHCHECK_OUTPUT_DIR` | healthcheck JSON 출력 |

카메라 IP·코덱 등은 프로젝트 `.env`에 두어도 된다. `python-dotenv`는 **이미 설정된 환경변수를 덮어쓰지 않으므로** `/etc/cam-acq/cam-acq.env`의 경로 설정이 우선한다.

운영 시 프로젝트를 `/opt/cam-acq` 등으로 옮기면 `CAM_ACQ_ROOT`와 unit 파일의 `WorkingDirectory`·`ExecStart` 경로를 함께 수정한다.

---

## 4. unit 파일 설치

경로가 `/home/besolt/works/cam_acq`가 아니면 `.service` 안의 `WorkingDirectory`, `ExecStart`를 실제 경로로 바꾼다.

### 4.1 Monitoring (지금 등록 가능)

```bash
sudo cp deploy/systemd/cam-acq-monitoring.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cam-acq-monitoring.service   # 부팅 시 자동 시작 (원할 때만)
sudo systemctl start cam-acq-monitoring.service
sudo systemctl status cam-acq-monitoring.service
journalctl -u cam-acq-monitoring.service -f
```

기본 포트는 `.env`의 `MONITORING_WEB_PORT` (미설정 시 config 기본값).

### 4.2 Acquisition (메인 파이프라인 — 아직 미등록)

YOLO + 자동 trigger 녹화 통합 데몬(Phase 4.3)이 생기기 전까지는 **등록하지 않는다**.

템플릿: `cam-acq-acquisition.service.example` — 통합 entry point 확정 후 복사·`ExecStart` 수정.

---

## 5. 수동 실행 vs 서비스 (개발 중)

개발·현장 검증은 서비스 없이:

```bash
export LD_LIBRARY_PATH=$PWD/sdk/Galaxy_camera/c/lib/x86_64:$LD_LIBRARY_PATH
uv run cam-acq-record-test --duration 28 --trigger-at 8
uv run cam-acq-yolo-live --duration 60
```

서비스 유저로 동작만 확인할 때:

```bash
sudo -u cam-acq env CAM_ACQ_ROOT=/path/to/cam_acq \
  /path/to/cam_acq/deploy/systemd/cam-acq-run.sh cam-acq-record-test \
  --duration 28 --trigger-at 8 \
  --output /var/lib/cam-acq/healthcheck/record_test.json
```

리포트 `storage.is_fallback: false`이고 `storage.path`가 `/mnt/data_pool/recordings`이면 primary 정상.

---

## 6. 파일 목록

| 파일 | 설명 |
|------|------|
| `cam-acq-storage-setup.sh` | 유저·저장소 권한 일괄 설정 |
| `cam-acq-run.sh` | `LD_LIBRARY_PATH` + `.venv/bin/<cli>` 실행 |
| `cam-acq.env.example` | `/etc/cam-acq/cam-acq.env` 템플릿 |
| `cam-acq-monitoring.service` | 모니터링 대시보드 unit |
| `cam-acq-acquisition.service.example` | 메인 파이프라인 unit (미래) |

---

## 7. 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| `storage.is_fallback: true` | primary 쓰기 불가 | §2 `cam-acq-storage-setup.sh` 재실행 |
| `primary_reject_reason: Permission denied` | `recordings`가 `750`이고 실행 유저가 `cam-acq` 그룹 아님 | §2 재실행 + **SSH 재접속**; `groups`에 `cam-acq` 확인 |
| SFTP로 `recordings` 접근 불가 | 동일 (besolt가 그룹 밖) | `sudo usermod -aG cam-acq besolt` 후 재접속; `chmod 2770` |
| `missing .venv/bin/...` | venv 미설치 | `sudo -u cam-acq`로 `cd $CAM_ACQ_ROOT && uv sync` |
| GPU 메트릭 실패 | 그룹 미가입 | `groups cam-acq`에 `video`, `render` 확인 |
| Galaxy SDK 로드 실패 | `LD_LIBRARY_PATH` | `cam-acq-run.sh` 경유 여부 확인 |
