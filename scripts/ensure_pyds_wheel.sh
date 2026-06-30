#!/usr/bin/env bash
# Symlink DeepStream prebuilt pyds wheel into vendor/ for uv (idempotent).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DS_ROOT="${DEEPSTREAM_ROOT:-/opt/nvidia/deepstream/deepstream}"
DIST="${DS_ROOT}/sources/deepstream_python_apps/bindings/dist"
PYPROJECT="${ROOT}/pyproject.toml"

mkdir -p "${ROOT}/vendor"
shopt -s nullglob
wheels=("${DIST}"/pyds-*-cp312-*.whl)
shopt -u nullglob

if ((${#wheels[@]} == 0)); then
  echo "pyds wheel not found in ${DIST}" >&2
  echo "Install DeepStream deepstream_python_apps bindings, or set DEEPSTREAM_ROOT." >&2
  exit 1
fi

wheel="${wheels[-1]}"
base="$(basename "${wheel}")"
target="${ROOT}/vendor/${base}"

# Drop stale vendor pyds wheels (version bumps).
shopt -s nullglob
for old in "${ROOT}"/vendor/pyds-*.whl; do
  if [[ "${old}" != "${target}" ]]; then
    rm -f "${old}"
  fi
done
shopt -u nullglob

ln -sf "${wheel}" "${target}"
echo "vendor/${base} -> ${wheel}"

# Keep pyproject [tool.uv.sources] path in sync with linked wheel name.
if grep -q '^pyds = { path = "vendor/pyds-' "${PYPROJECT}"; then
  sed -i "s|^pyds = { path = \"vendor/pyds-[^\"]*\" }|pyds = { path = \"vendor/${base}\" }|" "${PYPROJECT}"
fi
