#!/usr/bin/env bash
# Run ovweb rootless in a single container.
#
# Since Phase 4.6 the libopenvizsla supervisor runs inside ov-api's own
# process (no sidecar, no UNIX sockets). The container needs USB device
# access: we bind /dev/bus/usb so the in-process pyusb enumerator can list
# every FT2232H on the host, and the supervisor can later open the board
# libopenvizsla auto-matches. SELinux `container_t` cannot read
# `usb_device_t` by default, so we drop confinement with `label=disable`.
# For production hardening, ship a targeted policy module granting
# container_t access to usb_device_t.
#
# Env:
#   IMAGE_NAME        image tag (default: ovweb-api:latest)
#   OV_DATA_DIR       persistent session DB dir
#                     (default: $HOME/.local/share/ovweb)
#   OV_PORT           host port for the web UI (default: 8000)
#   EXTRA_PODMAN_ARGS anything else to append to podman run

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-ovweb-api:latest}"
OV_DATA_DIR="${OV_DATA_DIR:-$HOME/.local/share/ovweb}"
OV_PORT="${OV_PORT:-8000}"

mkdir -p "$OV_DATA_DIR"

# Preflight: warn (but don't block) if no OpenVizsla 3 is currently attached.
# The UI surfaces the zero-device case explicitly via GET /api/devices, so we
# can still boot the API and let the user plug a board in afterwards.
if ! lsusb 2>/dev/null | grep -qE '1d50:607c|0403:6010'; then
    echo "warn: no OpenVizsla 3 detected on this host (looked for 1d50:607c or 0403:6010)." >&2
    echo "      ov-api will start anyway; plug a board and click Rescan in the UI." >&2
fi

echo "info: ovweb on http://127.0.0.1:${OV_PORT}/  (Ctrl-C to stop)"
echo "info: data dir   = $OV_DATA_DIR"

# shellcheck disable=SC2086
exec podman run --rm -it \
    --name ov-api \
    --userns=keep-id \
    --user "$(id -u):$(id -g)" \
    --security-opt label=disable \
    -v /dev/bus/usb:/dev/bus/usb \
    -v "$OV_DATA_DIR:/data:Z" \
    -p "127.0.0.1:${OV_PORT}:8000" \
    -e OV_DB_PATH=/data/ovweb.sqlite \
    ${EXTRA_PODMAN_ARGS:-} \
    "$IMAGE_NAME" "$@"
