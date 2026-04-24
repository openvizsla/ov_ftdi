#!/usr/bin/env bash
# Build the ovweb gateware toolchain image (Xilinx ISE 14.7 + migen/misoc deps).
#
# Usage:
#   ./build-image.sh                 # build with default tag
#   IMAGE_NAME=foo:bar ./build-image.sh
#
# The build context is this directory, which must contain the ISE 14.7 tarball
# (~6.5 GB). First build takes 30-60 minutes and produces an image of ~20 GB.

set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

IMAGE_NAME="${IMAGE_NAME:-ovweb-gateware:ise14.7}"
TARBALL="Xilinx_ISE_DS_Lin_14.7_1015_1.tar"

if [[ ! -f "$TARBALL" ]]; then
    echo "error: $TARBALL not found in $(pwd)" >&2
    echo "       Download the ISE 14.7 full installer from xilinx.com and drop it here." >&2
    exit 1
fi

echo "info: building $IMAGE_NAME from $(pwd)"
echo "info: this will take a while; the installer extracts ~8 GB and runs batchxsetup."

exec podman build -t "$IMAGE_NAME" -f Containerfile .
