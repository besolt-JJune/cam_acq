#!/bin/bash
# Create cam-acq system user and grant write access to STORAGE_PATH.
# Shared group lets SFTP/dev user (e.g. besolt) read recordings too.
# Run once on the host: sudo ./deploy/systemd/cam-acq-storage-setup.sh
set -euo pipefail

CAM_ACQ_USER="${CAM_ACQ_USER:-cam-acq}"
CAM_ACQ_GROUP="${CAM_ACQ_GROUP:-cam-acq}"
STORAGE_PATH="${STORAGE_PATH:-/mnt/data_pool/recordings}"
STATE_DIR="${STATE_DIR:-/var/lib/cam-acq}"
# Space-separated extra users that need SFTP / dev access (e.g. besolt)
STORAGE_GROUP_USERS="${STORAGE_GROUP_USERS:-besolt}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root: sudo $0" >&2
  exit 1
fi

if ! getent group "${CAM_ACQ_GROUP}" &>/dev/null; then
  groupadd --system "${CAM_ACQ_GROUP}"
  echo "created group ${CAM_ACQ_GROUP}"
fi

if ! id "${CAM_ACQ_USER}" &>/dev/null; then
  useradd --system --home-dir "${STATE_DIR}" --gid "${CAM_ACQ_GROUP}" \
    --shell /usr/sbin/nologin "${CAM_ACQ_USER}"
  echo "created user ${CAM_ACQ_USER}"
else
  usermod -g "${CAM_ACQ_GROUP}" "${CAM_ACQ_USER}" 2>/dev/null || true
fi

usermod -aG video,render "${CAM_ACQ_USER}" 2>/dev/null || true

for u in ${STORAGE_GROUP_USERS}; do
  if id "${u}" &>/dev/null; then
    usermod -aG "${CAM_ACQ_GROUP}" "${u}"
    echo "added ${u} to group ${CAM_ACQ_GROUP}"
  fi
done

BRANCH_ROOT="$(dirname "${STORAGE_PATH}")"
mkdir -p "${STORAGE_PATH}" "${STATE_DIR}"/{logs,healthcheck,recordings}
chown "${CAM_ACQ_USER}:${CAM_ACQ_GROUP}" "${STORAGE_PATH}"
chmod 2770 "${STORAGE_PATH}"
chown -R "${CAM_ACQ_USER}:${CAM_ACQ_GROUP}" "${STATE_DIR}"
chmod 750 "${STATE_DIR}"

# ponytail: parent /mnt/data_pool stays root:root for OpenSSH ChrootDirectory safety
if [[ -d "$(dirname "${STORAGE_PATH}")" ]]; then
  chown root:root "$(dirname "${STORAGE_PATH}")"
  chmod 755 "$(dirname "${STORAGE_PATH}")"
fi

sudo -u "${CAM_ACQ_USER}" touch "${STORAGE_PATH}/.cam_acq_write_test"
sudo -u "${CAM_ACQ_USER}" rm -f "${STORAGE_PATH}/.cam_acq_write_test"

# ACL on mergerfs path + both branches (group perms alone are unreliable on mergerfs)
if command -v setfacl &>/dev/null; then
  BRANCH_ROOT="$(dirname "${STORAGE_PATH}")"
  ACL_PATHS=("${STORAGE_PATH}")
  for br in /mnt/ssd1 /mnt/ssd2; do
    [[ -d "${br}/$(basename "${STORAGE_PATH}")" ]] && ACL_PATHS+=("${br}/$(basename "${STORAGE_PATH}")")
  done
  for p in "${ACL_PATHS[@]}"; do
    setfacl -m "u:${CAM_ACQ_USER}:rwx" "${p}"
    setfacl -d -m "u:${CAM_ACQ_USER}:rwx" "${p}"
    setfacl -m "g:${CAM_ACQ_GROUP}:rwx" "${p}"
    setfacl -d -m "g:${CAM_ACQ_GROUP}:rwx" "${p}"
    for u in ${STORAGE_GROUP_USERS}; do
      if id "${u}" &>/dev/null; then
        setfacl -m "u:${u}:rwx" "${p}"
        setfacl -d -m "u:${u}:rwx" "${p}"
      fi
    done
  done
  echo "set ACL on: ${ACL_PATHS[*]}"
fi

# mergerfs caches supplemental groups; remount after usermod so new members take effect
if mountpoint -q "${BRANCH_ROOT}" 2>/dev/null; then
  mount -o remount "${BRANCH_ROOT}" || true
  echo "remounted ${BRANCH_ROOT} (refresh mergerfs group cache)"
fi

echo "OK: ${CAM_ACQ_USER} can write to ${STORAGE_PATH}"
echo "Verify as dev user: touch ${STORAGE_PATH}/.write_test"
echo "If still denied: newgrp ${CAM_ACQ_GROUP}  OR  sg ${CAM_ACQ_GROUP} -c 'touch ...'"
