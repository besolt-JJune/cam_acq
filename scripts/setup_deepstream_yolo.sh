#!/usr/bin/env bash
# Clone and build DeepStream-Yolo custom parser (Phase 3.2 prerequisite).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DS_YOLO="${ROOT}/third_party/DeepStream-Yolo"

if [[ ! -d "${DS_YOLO}/.git" ]]; then
  git clone --depth 1 https://github.com/marcoslucianops/DeepStream-Yolo.git "${DS_YOLO}"
fi

# DS 9.0 on this host: CUDA 13.1
export CUDA_VER="${CUDA_VER:-13.1}"

make -C "${DS_YOLO}/nvdsinfer_custom_impl_Yolo" clean
make -C "${DS_YOLO}/nvdsinfer_custom_impl_Yolo"

echo "Built: ${DS_YOLO}/nvdsinfer_custom_impl_Yolo/libnvdsinfer_custom_impl_Yolo.so"
