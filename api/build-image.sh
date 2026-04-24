#!/usr/bin/env bash
# Build the ov-api image (FastAPI + ingest + built Svelte UI + tshark).
#
# Build context is the repo root, NOT api/ — the Containerfile copies both
# api/ and frontend/. The .containerignore at repo root keeps the context
# lean (excludes ov_ftdi/, Xilinx tarball, node_modules, etc.).
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")/.."

IMAGE_NAME="${IMAGE_NAME:-ovweb-api:latest}"

exec podman build -t "$IMAGE_NAME" -f api/Containerfile .
