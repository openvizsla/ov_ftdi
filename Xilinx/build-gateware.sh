#!/usr/bin/env bash
# Run `make` in ov_ftdi/software/fpga/ov3 using the containerised ISE 14.7.
#
# On success, produces (on the host):
#   $OV_FTDI/software/fpga/ov3/build/ov3.bit
#   $OV_FTDI/software/fpga/ov3/build/ov3.fwpkg
#
# Env:
#   IMAGE_NAME            image tag (default: ovweb-gateware:ise14.7)
#   OV_FTDI               path to ov_ftdi checkout (default: parent of this script,
#                         i.e. the ov_ftdi fork when Xilinx/ lives inside it)
#   XILINXD_LICENSE_FILE  path to Xilinx.lic on the host (default: ~/.Xilinx/Xilinx.lic)

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-ovweb-gateware:ise14.7}"
OV_FTDI="${OV_FTDI:-$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)}"
LICENSE_FILE="${XILINXD_LICENSE_FILE:-$HOME/.Xilinx/Xilinx.lic}"

if [[ ! -d "$OV_FTDI" ]]; then
    echo "error: ov_ftdi not found at $OV_FTDI (set OV_FTDI=/path to override)" >&2
    exit 1
fi

if ! podman image exists "$IMAGE_NAME"; then
    echo "error: image $IMAGE_NAME not found. Run ./build-image.sh first." >&2
    exit 1
fi

# The container has no network, so submodules must be populated on the host.
# Two URL oddities in the transitive submodule tree:
#  - ov_ftdi/.gitmodules points migen at git://github.com/... which GitHub
#    retired in 2021. Remap git:// -> https://.
#  - misoc/.gitmodules has nested submodules (compiler_rt, libunwind) pointing
#    at http://llvm.org/git/... which was retired when LLVM moved to GitHub
#    in 2019. These belong to misoc's soft-CPU software runtime, which OV3
#    does not use (OV3 is pure HDL, no soft CPU). So we init the top-level
#    submodules only, without --recursive.
if [[ ! -f "$OV_FTDI/software/fpga/migen/setup.py" || \
      ! -f "$OV_FTDI/software/fpga/misoc/setup.py" ]]; then
    echo "info: initialising migen/misoc submodules in $OV_FTDI ..."
    git -C "$OV_FTDI" \
        -c url."https://github.com/".insteadOf="git://github.com/" \
        submodule update --init \
            software/fpga/migen \
            software/fpga/misoc
fi

license_args=()
if [[ -f "$LICENSE_FILE" ]]; then
    license_args+=(-v "$LICENSE_FILE:/opt/Xilinx/license/Xilinx.lic:ro,Z")
    echo "info: using license file $LICENSE_FILE"
else
    echo "warning: no license file at $LICENSE_FILE." >&2
    echo "         Spartan-6 LX9 is a WebPACK-free device but ISE still expects a .lic." >&2
    echo "         Register a free WebPACK license at xilinx.com and drop the file at $LICENSE_FILE." >&2
fi

exec podman run --rm -it \
    --userns=keep-id \
    --user "$(id -u):$(id -g)" \
    -v "$OV_FTDI:/work:Z" \
    "${license_args[@]}" \
    -w /work/software/fpga/ov3 \
    "$IMAGE_NAME" \
    "$@"
