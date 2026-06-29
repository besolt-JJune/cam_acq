# Ubuntu 추가 SSD 탈착형 자동 마운트 가이드 (MergerFS 활용)

본 가이드는 Ubuntu 환경에서 2개의 추가 SSD를 장착하고, 용량이 가득 찼을 때 물리적으로 디스크를 교체(Swap)하면서도 항상 동일한 경로에 자동으로 안전하게 마운트하여 사용할 수 있는 통합 스토리지 구성 방법을 다룹니다.

물리적 디스크가 교체되면 디스크 고유의 UUID가 변경되므로, 본 가이드에서는 고정된 **파일 시스템 라벨(Label)**과 파일 단위 결합 솔루션인 **MergerFS**를 조합하여 직관적이고 안정적인 시스템을 구축합니다.

---

## 전체 구성 요약
* **물리 디스크 1 (`/dev/sdb1`)** → 라벨: `VISION_1` → 마운트 경로: `/mnt/ssd1`
* **물리 디스크 2 (`/dev/sdc1`)** → 라벨: `VISION_2` → 마운트 경로: `/mnt/ssd2`
* **통합 가상 경로 (MergerFS)** → 마운트 경로: `/mnt/vision_pool` (최종 프로그램이나 서비스가 바라볼 경로)

---

## 1단계: 디스크 장착 및 장치명 확인

새로운 SSD 2개를 서버에 물리적으로 장착한 후 시스템에서 정상적으로 인식하는지 확인합니다.

```bash
lsblk
```

**출력 예시 파악:**
* 새로 장착한 디스크가 보통 `sdb`, `sdc` 또는 `nvme1n1`, `nvme2n1` 형태로 나타납니다.
* 본 가이드에서는 디스크 장치명을 `/dev/sdb`와 `/dev/sdc`로 가정하고 진행합니다. *자신의 환경에 맞는 장치명으로 변경하세요.*

---

## 2단계: 개별 SSD 포맷 및 라벨(Label) 지정

각 디스크에 물리적 식별자 대신 고정으로 사용할 라벨(`VISION_1`, `VISION_2`)을 부여하며 포맷합니다. **향후 디스크를 새것으로 교체할 때도 이 단계를 동일하게 수행해야 합니다.**

```bash
# 1. 첫 번째 SSD 포맷 및 라벨 지정
sudo mkfs.ext4 -L VISION_1 /dev/sdb

# 2. 두 번째 SSD 포맷 및 라벨 지정
sudo mkfs.ext4 -L VISION_2 /dev/sdc
```
*(주의: 기존에 파티션 테이블을 생성했다면 `/dev/sdb1`, `/dev/sdc1`과 같이 파티션 장치명에 실행합니다.)*

---

## 3단계: 마운트 디렉토리(포인트) 생성

개별 디스크가 연결될 경로와, 두 디스크가 하나로 합쳐져 보일 통합 경로를 각각 생성합니다.

```bash
# 개별 디스크 마운트 경로 생성
sudo mkdir -p /mnt/ssd1
sudo mkdir -p /mnt/ssd2

# MergerFS 통합 가상 경로 생성
sudo mkdir -p /mnt/vision_pool
```

---

## 4단계: MergerFS 패키지 설치

두 개의 독립된 마운트 경로를 하나의 폴더 구조로 묶어주는 MergerFS를 설치합니다.

```bash
sudo apt update
sudo apt install -y mergerfs
```

---

## 5단계: `/etc/fstab` 자동 마운트 설정

시스템이 재부팅되더라도 디스크 라벨을 기준으로 자동으로 마운트하고, MergerFS 가상 풀을 구성하도록 정적 파일 시스템 정보를 설정합니다.

```bash
sudo nano /etc/fstab
```

파일의 맨 아래에 다음 내용을 추가합니다.

```text
# [1] 개별 물리 디스크 자동 마운트 (라벨 기준, nofail 필수)
LABEL=VISION_1  /mnt/ssd1  ext4  defaults,nofail  0  2
LABEL=VISION_2  /mnt/ssd2  ext4  defaults,nofail  0  2

# [2] MergerFS 통합 마운트 설정 (두 경로를 하나로 합침)
/mnt/ssd1:/mnt/ssd2  /mnt/vision_pool  fuse.mergerfs  defaults,allow_other,use_ino,category.create=mfs,fsname=mergerfs  0  0
```

> **💡 핵심 옵션 설명:**
> * `nofail`: 디스크가 탈착되어 물리적으로 존재하지 않는 상태에서 재부팅하더라도, 에러로 인해 부팅이 멈추는(Emergency Mode) 현상을 방지하고 정상 부팅되도록 합니다.
> * `category.create=mfs`: 새로운 파일이 생성될 때, 연결된 디스크들(`ssd1`, `ssd2`) 중 **남은 용량이 가장 많은 곳(Most Free Space)**에 자동으로 파일을 분산 저장합니다.

---

## 6단계: 마운트 테스트 및 최종 확인

시스템을 재부팅하지 않고 설정이 올바르게 되었는지 즉시 반영하고 확인합니다.

```bash
# 1. fstab 설정을 기반으로 전체 마운트 실행
sudo mount -a

# 2. 마운트 상태 및 용량 확인
df -h
```

`/mnt/vision_pool` 경로의 전체 용량이 두 개의 SSD 용량을 합친 크기로 정상 출력되는지 확인합니다. 앞으로 데이터를 저장하거나 읽을 때는 오직 `/mnt/vision_pool` 경로만 사용하면 됩니다.

---

## 7단계: 디스크 만료 시 물리적 교체(Swap) 워크플로우

용량이 가득 찬 디스크를 빼고 새 디스크로 교체할 때는 아래 프로세스를 엄격히 준수해야 데이터 유실을 방지할 수 있습니다. (예: 1번 디스크 `VISION_1` 교체 가정)

1. **안전한 마운트 해제 (Unmount):**
   ```bash
   sudo umount /mnt/ssd1
   ```
2. **물리적 탈착 및 교체:**
   * 서버에서 용량이 꽉 찬 SSD를 제거합니다. (제거된 SSD에는 기존 데이터가 `ext4` 형태로 온전히 보존되어 있으므로 다른 시스템이나 워크스테이션에 연결해 바로 읽을 수 있습니다.)
   * 비어 있는 새 SSD를 장착합니다.
3. **새 디스크 라벨 포맷 (2단계와 동일):**
   * 새 디스크의 장치명(예: `/dev/sdb`)을 확인한 후 기존과 **동일한 라벨**로 포맷합니다.
   ```bash
   sudo mkfs.ext4 -L VISION_1 /dev/sdb
   ```
4. **재마운트 적용:**
   ```bash
   sudo mount -a
   ```
   * 시스템은 자동으로 새 디스크를 `/mnt/ssd1`에 연결하고, MergerFS는 비어 있는 공간을 인식하여 다시 `/mnt/vision_pool`에 결합합니다. 시스템 재부팅 없이도 즉시 연속적인 데이터 적재가 가능해집니다.