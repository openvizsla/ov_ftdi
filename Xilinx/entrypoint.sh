#!/usr/bin/env bash
# Source the ISE env and exec the user's command. Writable HOME required
# because ISE touches ~/.Xilinx/ for runtime state.
set -e

if [[ -z "${HOME:-}" || ! -w "${HOME:-/nonexistent}" ]]; then
    export HOME=/tmp
fi

if [[ -r /opt/Xilinx/14.7/ISE_DS/settings64.sh ]]; then
    # settings64.sh is noisy and returns nonzero on some edge cases; swallow both.
    set +e
    source /opt/Xilinx/14.7/ISE_DS/settings64.sh >/dev/null 2>&1 || true
    set -e
fi

exec "$@"
