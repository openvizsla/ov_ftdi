# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: ovweb

OpenVizsla 3.2 USB protocol analyzer with a self-hosted web UI and Claude-assisted protocol analysis. Captures USB 1.1/2.0 traffic on the local host, decodes it via tshark, stores sessions in SQLite, and exposes an async analysis endpoint that uses the Anthropic API (tool-use) to produce protocol summaries and skeleton driver code from real captures.

Targets general-purpose USB device classes (HID, UVC, MSC, CDC, audio) and vendor-specific protocols.

## Hardware context (read this before touching capture code)

**Board:** OpenVizsla 3.2 (genuine Kickstarter hardware), based on:

- FTDI FT2232H (USB ↔ FPGA transport, sync FIFO + JTAG)
- Xilinx Spartan-6 LX9 (`XC6SLX9-3TQG144C`) running migen-generated gateware
- USB3343 ULPI PHY for the target tap
- 16-bit SDRAM buffer

**No on-board bitstream flash.** The FPGA is configured at every power-up by the host software via the FT2232H. There is nothing to flash persistently. Bitstream load happens at the start of every capture session.

**USB connectors:**

- `J1` — host side (cable to the analysis machine, the i7)
- `J2` / `J3` — target pass-through (device under analysis goes here)

**Headers (do not confuse):**

- `P1` (1×9) — external FPGA JTAG; cuttable trace ("cut for ext JTAG") isolates from FTDI-driven JTAG
- `P2` (2×7) — target ULPI breakout (PHY signals; do not use for general I/O)
- `P3` (2×17) — FTDI ↔ FPGA config/FIFO bus + FPGA JTAG mirror; debug only
- `P4` (2×13) — 20 spare FPGA GPIOs (`SPARE0..SPARE19`) on Bank 1, 3.3 V LVCMOS; **not used by this project**
  - `SPARE9` is tied to U5 (50 MHz oscillator) via R1 — only 19 are usable if anyone ever cares
- `J4` / `J5` — SMA trigger in/out; **not used by this project**

The host USB cable supplies power. No external supply.

## Architecture

One rootless Podman container (`ovweb-api`). The libopenvizsla supervisor
runs in-process inside the FastAPI app; the former `ov-capture` sidecar and
its two UNIX sockets were collapsed into a single image in Phase 4.6.

```
FT2232H (USB)
    │
    ▼
ovweb-api      libopenvizsla (ctypes) + FastAPI + tshark + SQLite + static UI
    │
    ▼  HTTPS / optional reverse proxy (out of scope for this project)
browser
```

The supervisor produces pcap (linktype 288, USB 2.0 LINK_LAYER) on an
in-process `asyncio.Queue`, `tshark -T fields` is spawned per live session
to reassemble transfers, which are persisted to SQLite unconditionally.
The WebSocket fan-out is channel-masked: subscribers pick any subset of
`summary` (per-endpoint live table), `events` (filtered notable events),
and `firehose` (raw per-transfer stream). Default is `summary + events`;
the browser's default view never shows the raw NAK flood.

LLM integration is server-side only: Claude is called from `ovweb-api` via
the Anthropic Python SDK. The browser never sees the API key.

## Tech stack (decided; do not relitigate without reason)

| Layer | Choice | Why |
|---|---|---|
| Capture daemon | `libopenvizsla` (C) wrapped by a thin Python supervisor | Stable, used by Wireshark extcap; `ovctl.py` upstream is a CLI demo, not a library |
| Decode | `tshark -T json` per session | Free, accurate USB class dissectors (HID, UVC, MSC, CDC, audio) |
| Vendor decoders | Python plugins under `ingest/decoders/` | Only when tshark output is insufficient |
| Storage | SQLite + WAL; one DB file + one pcap archive per session | Fits scale; revisit only on real pain |
| Backend | FastAPI (async), Pydantic v2, uvicorn | Async-native, fits WS + tool-use workload |
| Frontend | Svelte + TypeScript, `@tanstack/virtual` for packet lists | Minimal runtime, fast iteration; keep it boring |
| Container runtime | Rootless Podman with quadlets, CDI for device passthrough | Project-wide convention |
| LLM | Anthropic Python SDK, Claude with tool use | Server-side only |

## Repository layout

The ovweb work lives at the root of the ov_ftdi fork. Upstream gateware
content (`docs/`, `hardware/`, `software/`) is unchanged; everything else is
new in this phase.

```
ov_ftdi/                                  # this fork
├── README.md                             # upstream fork README (untouched)
├── OVWEB.md                              # ovweb user-facing README (this phase)
├── CLAUDE.md                             # this file
├── .gitignore                            # upstream + ovweb additions
├── .gitmodules                           # migen, misoc (upstream) + libopenvizsla (new)
├── .containerignore                      # podman build-context excludes
├── docs/  hardware/  software/           # upstream fork contents, untouched except:
│   └── software/host/52-openvizsla.rules # upgraded to TAG+="uaccess" (was plugdev+0666)
├── api/                                  # ovweb-api Python project (uv)
│   ├── Containerfile                     # 3 stages: libopenvizsla + ui + runtime
│   ├── build-image.sh  run.sh
│   ├── pyproject.toml  uv.lock
│   ├── src/ovweb/
│   │   ├── app.py                        # FastAPI + WebSocket + /api/devices + lifespan
│   │   ├── db.py                         # sqlite3 connect + apply migrations
│   │   ├── live_ingest.py                # broadcaster queue → FIFO → tshark → FSM → WS/DB
│   │   ├── migrations/001_initial.sql
│   │   ├── capture/                      # in-process libopenvizsla supervisor
│   │   │   ├── supervisor.py             # ctypes + asyncio; lazy device open
│   │   │   ├── client.py                 # CaptureClient wrapper (keeps app.py stable)
│   │   │   └── devices.py                # pyusb enumeration for GET /api/devices
│   │   ├── ingest/
│   │   │   ├── tshark.py                 # pcap → UsbLinkPacket stream (tshark -T fields)
│   │   │   ├── reassembly.py             # Reassembler FSM (feed/flush)
│   │   │   └── filter.py                 # LiveFilter: summary + events + firehose
│   │   └── cli/decode_session.py         # `decode-session raw.pcap -> session.sqlite`
│   ├── third_party/libopenvizsla/        # submodule → matwey/libopenvizsla @ 0.2.0
│   └── tests/
├── frontend/                             # Svelte 4 + Vite 5 (pnpm); the container
│   │                                     # rebuilds dist into api/src/ovweb/ui/ at build time
│   ├── package.json  pnpm-lock.yaml  vite.config.ts
│   └── src/{App.svelte, api.ts, main.ts}
└── Xilinx/                               # ISE 14.7 toolchain container (gateware)
    ├── Containerfile  install_config.txt  xsetup_expect.sh  entrypoint.sh
    ├── build-image.sh  build-gateware.sh
    └── Xilinx_ISE_DS_Lin_14.7_1015_1.tar # 6.5 GB installer, gitignored
```

Out of scope for this PR: `quadlets/` (systemd `--user` auto-start),
`compose-dev.yml`, and `api/src/ovweb/analyze/` (Phase 5 LLM worker). All
three are tracked but deferred.

## Gateware build (Xilinx ISE 14.7, containerised)

Spartan-6 is supported only by ISE 14.7, which Xilinx discontinued and which does not run natively on modern Linux. We ship a rootless-Podman container under `Xilinx/` that bakes ISE 14.7 WebPACK into an image; `ov_ftdi/software/fpga/ov3` builds inside it via a bind-mounted workspace.

**One-time image build** (~30–60 min, ~20 GB final image):

```sh
cd Xilinx/
./build-image.sh
```

This expects `Xilinx/Xilinx_ISE_DS_Lin_14.7_1015_1.tar` (the ~6.5 GB ISE installer) to be present. The tarball must not be committed.

**Build the bitstream:**

```sh
./build-gateware.sh              # default: `make all` -> ov3.bit + ov3.fwpkg
./build-gateware.sh make clean   # override the CMD
```

Outputs (on the host, under `ov_ftdi/software/fpga/ov3/build/`): `ov3.bit`, `ov3.fwpkg`. The `.fwpkg` is what `ovctl.py` / the capture supervisor loads at session start.

**License:** Spartan-6 LX9 is a WebPACK-free device, but ISE still expects a node-locked `.lic`. Register a free WebPACK license at xilinx.com, drop the file at `~/.Xilinx/Xilinx.lic`, and `build-gateware.sh` will bind-mount it. Override path via `XILINXD_LICENSE_FILE`.

**Workarounds baked into the image:**
- `libPortability.so` replaced with `libPortabilityNOSH.so` (removed `stat64` symbol on modern glibc).
- Bundled `libstdc++.so.6` renamed so the system one is used.

**Things to know:**
- The container has no network. `build-gateware.sh` initialises `migen`/`misoc` submodules on the host before calling `podman run`.
- `--userns=keep-id` maps the host UID inside so build artefacts end up owned by the user.
- Rebuilding the image is only necessary when the toolchain or `install_config.txt` changes — not on every gateware edit.

Do not modify `ov_ftdi/software/fpga/ov3` sources in this repo. If gateware changes are needed, fork `ov_ftdi` upstream, pin the fork, and document the change reason in CLAUDE.md.

## Capture supervisor (in-process, `api/src/ovweb/capture/`)

Since Phase 4.6 the libopenvizsla supervisor is not a sidecar — it runs as
an asyncio task inside the FastAPI app. `Supervisor.open()` (from lifespan)
loads `libopenvizsla.so` via ctypes and sets up the in-process
`PcapBroadcaster`; **it does not claim the USB device**. The device is
opened lazily on `supervisor.start(speed)` (invoked by `POST /api/sessions`)
and released on `stop()`. This lets the API boot on a host without an OV3
attached; the UI reports "no devices" until one is plugged in and Rescan
is hit.

The capture loop runs on a pthread inside libopenvizsla; the packet
callback marshals each pcap record to the asyncio loop via
`loop.call_soon_threadsafe`. `PcapBroadcaster.register()` returns an
`asyncio.Queue[bytes]` that `LiveSession._packet_stream` drains into the
tshark FIFO.

**Speed retry is disabled in the API surface.** `POST /api/sessions` takes
`speed ∈ {ls, fs, hs}` explicitly; `auto` is accepted by `Supervisor.start`
internally but not exposed, because the libopenvizsla HS→FS→LS probe wedge
(see "Things that are easy to get wrong") makes it unsafe.

**Timestamps:** the 60 MHz OV counter is converted to wall-clock
nanoseconds by anchoring `(first_packet_ov_ts, time.time_ns())` on the
first post-lock packet, then emitting deltas. No drift correction across
sessions; revisit only if real drift bites.

**Run:**
```sh
api/build-image.sh    # one-time build (libopenvizsla + UI + Python deps)
api/run.sh            # starts ovweb; -v /dev/bus/usb + label=disable
```

`run.sh` bind-mounts `/dev/bus/usb` read-write so pyusb can enumerate and
libopenvizsla can claim; `--security-opt label=disable` is required because
`container_t` can't reach `usb_device_t` by default on SELinux-enforcing
hosts.

**Known non-fatal log noise:** libopenvizsla's dispatch returns `-2`
(`BREAK_LOOP`) on graceful stop; the supervisor suppresses that case. A
`-1` (`FATAL_ERROR`) with `error_str="Wrong packet magic"` during a
wrong-speed probe is expected — the decoder sees bus-line garbage because
the PHY isn't synced; treated as "probe did not lock" and moved on.

## Device enumeration (`api/src/ovweb/capture/devices.py`)

pyusb-based `enumerate()` yields `DeviceInfo(bus, address, port_path,
serial, vid, pid, description)` for every FT2232H matching `1d50:607c`
(OpenMoko EEPROM) or `0403:6010` (raw FTDI fallback). Serial strings are
best-effort (silently `None` if uaccess hasn't applied for the user).
Surfaced to the UI via `GET /api/devices`.

libopenvizsla 0.2.0's public API (`ov_new` → `cha_open` → `ftdi_usb_open`)
always opens the first VID/PID match — there is no way to select by
serial/bus/port. The UI warns when >1 OV3 is attached; actual
selection-by-serial is a Phase 4.7 deliverable that requires a libopenvizsla
C patch. `POST /api/sessions` accepts a `device_serial` field today as a
forward-compat hook; it's logged and ignored when the supervisor can't
honor it.

## Ingest CLI (`decode-session`)

Phase 3 deliverable: `api/src/ovweb/cli/decode_session.py`, a standalone tool that turns a raw OV3 pcap into a self-contained SQLite session DB. No HTTP, no UI, no live-capture — just `pcap -> tshark -T fields -> reassembly FSM -> sqlite3`.

**Install + run** (uv manages the venv):

```sh
cd api/
uv sync
uv run decode-session /path/to/raw.pcap --speed ls --out session.sqlite
```

Pipeline choices worth knowing:
- **tshark `-T fields`** instead of `-T json` for the link-layer pass. USBLL is flat, line-per-packet is cheaper than JSON streaming, and no extra parser dependency. When class-aware decoders land (HID, UVC, MSC) they'll need `-T json + ijson` because their dissection is nested — that's a separate pass on the same pcap.
- **Reassembly FSM** (`ingest/reassembly.py`) keyed by `(device_addr, endpoint)`. Handles TOKEN+DATA+HANDSHAKE and TOKEN+HANDSHAKE (NAK/STALL-only) flows. Isoch, HS PING/NYET split-transactions, SPLIT/PRE flows: **not yet handled** — left for a later pass, will add when real captures need them.
- **SOFs dropped at ingest** (same policy as the capture daemon). `--include-sofs` debug flag exists but SOFs are stripped from reassembly regardless.
- **Endpoint summary** (`observed_summary_json`) is derived from the transfer log in the same pass so reports don't re-scan the full table.

**Validated against** a USB LS HID boot keyboard (1.5 Mbps): 5093 packets → 2509 transfers in 0.11 s; 76 ACK'd interrupt-IN transfers on endpoint `19.1` carry the classic 8-byte HID report (`{modifiers, reserved, 6× keycodes}`). Keycodes round-trip correctly (`0x0a` = 'g', `0x09` = 'f').

## ovweb-api: REST + WebSocket (`uvicorn ovweb.app:app`)

Single FastAPI app over the session DB and the in-process `Supervisor`. The
OV3 is single-session hardware, so at most one `LiveSession` is active at a
time; starting a second one returns **409**.

**REST surface:**
- `GET  /api/health` — liveness
- `GET  /api/devices` — attached OV3 enumeration (pyusb) + `selected_policy`
- `GET  /api/sessions` — session list (descending by id, capped at 200)
- `GET  /api/sessions/{id}` — detail + endpoint summaries
- `GET  /api/sessions/{id}/transfers?offset=&limit=` — paginated transfers
- `POST /api/sessions` `{speed: "ls|fs|hs", notes?, device_serial?}` — preflight
  enumerates devices (400 if zero), opens the FTDI lazily, probes the speed,
  spawns `LiveSession` + `LiveFilter`, returns `{session_id, speed}`. `auto`
  is deliberately not exposed; `device_serial` is accepted and logged but
  ignored in 4.6 (see "Device enumeration").
- `POST /api/sessions/{id}/stop` — cancels ingest, closes the FTDI, rebuilds
  the endpoint summary table.
- `WS   /api/sessions/{id}/live` — channel-masked live feed (see below).
- `GET  /` → static UI (built Svelte bundle under `src/ovweb/ui/`). Missing
  UI is tolerated with a JSON placeholder.

**WebSocket contract** (three channels; default mask = summary + events):
```
Server -> {"type":"hello","channels_default":[...],"snapshot":{"endpoints":[...]}}
Client -> {"type":"subscribe","channels":["summary","events"]
                                       | ["summary","events","firehose"]}
Server -> {"type":"endpoint_update","updates":[EndpointStat,...]}   (summary)
Server -> {"type":"event","kind":"...","ts_ns":...,...}             (events)
Server -> {"type":"transfer","transfer":{...}}                      (firehose)
Server -> {"type":"end","packets":N,"transfers":M}   — all subscribers
Server -> {"type":"error","error":"..."}              — all subscribers
```
Events emitted by `LiveFilter`: `new_endpoint`, `control_transfer`,
`payload_change` (IN-ACK with byte-for-byte diff), `status_flip` (run-length
ack↔nak / stall / nyet / incomplete), `speed_locked`, `speed_lost`,
`overflow`. Summary ticks every 250 ms and flushes only changed rows.

**Env configuration:**
- `OV_DB_PATH` (default `./ovweb.sqlite`, `/data/ovweb.sqlite` in-container)
- `OV_UI_DIR` (default `<pkg>/ui`; set to `frontend/dist` for a rebuilt dev UI)
- `SPEED_PROBE_TIMEOUT` (default `2.0` seconds; per-speed deadline)

**Live-ingest pipeline quirks:**
- **FIFO instead of anonymous pipe.** `tshark -r -` aborts under
  `asyncio.create_subprocess_exec`'s pipe-stdin with `"standard input is a
  special file or socket"`. `tshark -i -` triggers dumpcap (needs wireshark
  group). Workaround: per-session FIFO via `tempfile.mkdtemp()` + `os.mkfifo`
  and `tshark -r <fifo>`. Writes are offloaded to `asyncio.to_thread` so the
  event loop stays responsive.
- **Stop via cancellation.** `LiveSession.stop()` cancels the ingest task
  rather than awaiting `_stop_event`; the task blocks inside
  `tshark.stdout.readline()` and cancellation is what actually unblocks it.
  Cleanup (FIFO unlink, tshark terminate, broadcaster unregister) runs in
  the `finally` of `_packet_stream`.
- **Persistence is always on.** Every reassembled `Transfer` is INSERTed
  into SQLite before `LiveFilter.on_transfer` runs. The filter only affects
  what's fanned out over the WebSocket.

**Dev loop (host-native, no container):**
```sh
# Terminal 1: API. `uv sync` first if you haven't.
cd api/
OV_DB_PATH=/tmp/ovweb.sqlite \
uv run uvicorn ovweb.app:app --host 127.0.0.1 --port 8000

# Terminal 2: frontend (Vite proxies /api and /api/**/live -> :8000)
cd frontend/
pnpm dev        # http://localhost:5173
# or one-shot for serving from the API:
pnpm build      # outputs into api/src/ovweb/ui/ (gitignored)
```

Host prerequisites for the non-container path: `libopenvizsla` + `libftdi1`
+ `libusb-1.0` + `tshark` installed, `udev/52-openvizsla.rules` applied
with the board replugged.

**Smoke-test result (Phase 4.6, in-container):** LS keyboard, 8 s window.
`POST /api/sessions speed=ls` returns `{session_id,speed:"ls"}`, WebSocket
receives `{type:"hello"}` with empty snapshot, then `speed_locked` event
(from the lazy-open + lock sequence), then 250 ms-cadence `endpoint_update`
batches as traffic arrives. A default-subscribed client sees **zero**
`transfer` messages (firehose opt-in); behind-the-scenes 632 transfers are
persisted for the same period. `POST /stop` rebuilds endpoint summaries.

## Capture: speed auto-retry

The OV3 cannot auto-detect target USB speed. The supervisor implements retry:

1. Start capture at HS (480 Mbps).
2. If no SOF observed within `SPEED_PROBE_TIMEOUT` (default 2 s), tear down, restart at FS (12 Mbps).
3. If no SOF within timeout, restart at LS (1.5 Mbps).
4. If still nothing, mark `speed=unknown` on the session and stop. Do not loop.

Once a speed locks (SOFs flowing), record it on the session row and never switch mid-session. To recapture, the user starts a new session.

`SPEED_PROBE_TIMEOUT` is configurable via env. Do not hardcode in business logic.

## Ingest pipeline

1. **Capture** — libopenvizsla → pcap stream on UNIX socket.
2. **Tee** — supervisor writes raw pcap to `/data/sessions/{id}/raw.pcap` and forwards events to ingest.
3. **Decode** — tshark consumes pcap, emits per-packet JSON.
4. **Reassemble** — group packets into transfers (control SETUP+DATA+STATUS, bulk/int chunks, iso frames).
5. **Normalize** — write transfer rows + endpoint summary + descriptor cache into SQLite.
6. **Fan out** — push normalized events on the WebSocket.

SOF packets are dropped before reassembly unless an explicit "include SOFs" debug flag is set on the session. They are ~99% of HS traffic by count and ~0% useful for protocol analysis.

## Database schema (initial)

- `sessions(id, started_at, ended_at, speed, status, notes)`
- `descriptors(session_id, kind, index, raw_bytes, parsed_json)` — device, config, interface, endpoint, HID report, class-specific
- `transfers(id, session_id, ts, ep_addr, direction, type, setup_bytes, data_bytes, status, length)` — one row per logical transfer, not per packet
- `endpoints(session_id, ep_addr, type, mps, observed_summary_json)` — derived, rebuildable from transfers
- `analyses(id, session_id, started_at, model, prompt_version, tool_call_log_json, report_md, status)` — one row per `/analyze` invocation

Migrations: handwritten SQL in `api/src/ovweb/migrations/`, applied at app startup. Do not pull in Alembic for this scale.

## LLM analysis: tool-use surface

Claude is given a fixed toolset and asked to produce a protocol report + driver skeleton. **Never dump raw pcap or full transfer logs into the prompt.** The model drives via tools.

Initial tool set (kept deliberately small):

- `get_session_overview(session_id)` → speed, parsed descriptors, endpoint inventory, transfer counts per endpoint
- `list_control_requests(session_id)` → unique `(bmRequestType, bRequest, wValue, wIndex)` tuples with example payloads
- `get_endpoint_traffic(session_id, ep_addr, limit=50)` → sample transfers on one endpoint with hex payloads
- `search_payloads(session_id, hex_pattern, limit=20)` → find payloads matching a hex/regex pattern
- `get_descriptor(session_id, kind, index)` → full parsed descriptor

Prompts live in `api/src/ovweb/analyze/prompts.py`, versioned with the codebase. Each `analyses` row stores the prompt version, full tool call log, and final report so reruns are reproducible and diff-able.

**Output target:** a markdown report (protocol description, transfer flow, open questions) plus an optional pyusb / hidapi / libuvc skeleton. The report is the primary deliverable; the skeleton is best-effort.

**Cap maximum tool iterations per analysis** (suggest 25). Without a cap, a confused model can run up cost and time.

## Hard constraints

- **Rootless Podman only.** No `--privileged`. USB device access via udev `TAG+="uaccess"` and `AddDevice=` in the quadlet (CDI when available).
- **No system-wide changes** for capture. Everything scoped to the user, the udev rule, and the containers.
- **No browser ever holds the Anthropic API key.** All Claude calls server-side.
- **No telemetry, no external network calls** from `ov-capture` or `ov-api` except to the Anthropic API.
- **SQLite WAL mode** mandatory; concurrent reads during capture are a real workload.
- **Drop SOFs at ingest** unless explicitly requested.
- **Pin tshark major version** in the Containerfile. JSON output format has changed across Wireshark versions; do not float.

## Things that are easy to get wrong

- **Bitstream load latency.** First `ovctl.py sniff` after power-up takes a few seconds because the bitstream is being shipped over USB. Do not interpret this as a hang.
- **FT2232H EEPROM.** Some surplus boards shipped with blank or wrong EEPROMs. If `lsusb` shows the wrong VID:PID (expect `0403:6010`), reflash the EEPROM with `ftdi_eeprom` before debugging anything else.
- **udev rules require reload + re-trigger** (`udevadm control --reload && udevadm trigger`) and the device replugged. Forgetting this looks like a permissions bug.
- **SELinux + rootless Podman + `--device`.** On Fedora/RHEL with SELinux enforcing, the USB device node is labelled `usb_device_t`, which the default container domain (`container_t`) cannot read. Symptom inside the container: `ls /dev/bus/usb/<bus>/<dev>` prints `-?????????` and `open()` returns `EACCES` — even with the correct uaccess ACL. Workaround: `--security-opt label=disable` (what `capture/run.sh` does). For production, ship a targeted policy module granting `container_t` access to `usb_device_t`.
- **USB Low Speed has no SOFs.** At LS, the host sends **EOP keep-alives** every 1 ms instead of SOF tokens; SOFs only exist at FS (1 ms cadence) and HS (125 µs). The capture supervisor's speed-probe "lock" detector must therefore key off "any successfully decoded packet" rather than "PID == SOF", or LS captures will never lock even when the bus is perfectly healthy.
- **libopenvizsla HS→FS→LS probe wedging.** Attempting an HS probe on a non-HS bus and then transitioning to FS (via `ov_set_usb_speed` + new capture) sometimes leaves `ov_device` in a state where `ov_capture_breakloop` never actually exits the libusb loop. Symptom: supervisor's event loop blocks, `podman stop` falls through to SIGKILL. Workaround for now: specify the speed explicitly when the target is known; don't rely on auto-retry across speeds. Real fix is to fully `ov_free` + `ov_new` + `ov_open` between probe attempts; tracked as a Phase-2 follow-up.
- **tshark JSON output is one giant array per file.** For long captures, stream-parse with `ijson` rather than loading whole file. Memory blows up on multi-GB captures otherwise.
- **tshark on async subprocess stdin.** `tshark -r -` under `asyncio.create_subprocess_exec` with `stdin=PIPE` aborts with `"The standard input is a special file or socket..."`. Workaround in `live_ingest.py`: create a FIFO via `tempfile.mkdtemp()` + `os.mkfifo()`, pass it as `tshark -r <fifo>`, and pump pcap bytes into it via `asyncio.to_thread(fifo.write, chunk)`. `tshark -i -` is **not** an alternative — it invokes `dumpcap` which needs the `wireshark` group (system-wide config, out of scope). Same tshark under `subprocess.Popen` (sync) accepts pipe stdin just fine — this is an asyncio-pipe-specific quirk.
- **tshark stdout buffering under asyncio.** `tshark -T fields` is block-buffered when stdout is not a tty; `readline()` then appears to hang. Pass `-l` for line-buffered output. Already in `TSHARK_FIELDS_ARGS`.
- **USB/IP is not a feature of this project.** The OV3 is a physical inline tap; D+/D- cannot be tunneled. "Remote access" in this project means web access to captured sessions, not remote device passthrough.
- **LLM hallucination on encrypted / authenticated protocols.** Run an entropy heuristic on payloads at ingest; surface "likely-encrypted" as a finding in the report rather than letting the model invent a cipher.
- **Spartan-6 toolchain.** Only Xilinx ISE 14.7 supports it, and Xilinx discontinued it — it does not run natively on modern Linux. We build gateware via the containerised ISE 14.7 toolchain in `Xilinx/` (see the "Gateware build" section). Do not try to run `xsetup` or `make` in the `ov3/` tree directly on the host; use `Xilinx/build-gateware.sh`.
- **libopenvizsla device selection is single-match.** `ov_new` → `cha_open` → `ftdi_usb_open(OV_VENDOR, OV_PRODUCT)` always opens the first matching board; `device_serial` on `POST /api/sessions` is forward-compat only. Multi-OV3 hosts will hit "unable to claim usb device" if the first match is already claimed; unplug the others or wait for Phase 4.7.
- **Lazy device open + rebuild bitstream each session.** `Supervisor.open()` does NOT claim the USB device; that's deferred to `start(speed)` and released on `stop()`. Side-effect: the FPGA bitstream gets re-shipped on every capture start (~100 ms). Worth it for the "start ovweb without a board plugged in" UX.
- **SELinux + `/dev/bus/usb`.** `api/run.sh` uses `--security-opt label=disable` because `container_t` can't touch `usb_device_t` by default. For production hardening, ship a targeted policy module granting that access instead of disabling confinement.
- **Submodule URL drift.** `software/fpga/migen` points at `git://github.com/m-labs/migen.git` (GitHub retired `git://` in 2021). `Xilinx/build-gateware.sh` works around this with a transient `url.insteadOf` config; `git submodule update --init` on the command line will fail without that. `misoc`'s transitive submodules reference `http://llvm.org/git/...` (retired 2019) — `build-gateware.sh` intentionally skips `--recursive` since OV3 doesn't use misoc's soft-CPU runtime.

## Development phases

Shipped in this PR (Phase 0 through 4.6):

0. **Step zero: board bring-up.** Upstream `software/host/` built on the
   target host, udev rules applied, `ovctl.py sniff hs` prints packets using
   the upstream-shipped bitstream. ✅
1. **Gateware container.** `Xilinx/` wraps ISE 14.7 WebPACK; the OV3
   bitstream + fwpkg rebuild from `software/fpga/ov3` via
   `Xilinx/build-gateware.sh`. ✅
2. **libopenvizsla supervisor.** `matwey/libopenvizsla` pinned as submodule
   at tag `0.2.0`; `api/src/ovweb/capture/supervisor.py` drives it via
   ctypes + asyncio. ✅
3. **Ingest CLI.** `decode-session raw.pcap → session.sqlite`, validated
   against a USB LS HID boot keyboard (5093 packets → 2509 transfers,
   76 ACK'd interrupt-IN carrying the classic 8-byte HID boot report). ✅
4. **FastAPI + WebSocket + Svelte UI.** ✅ (Phase 4)
5. **Single container + filtered live UI + device picker.** ✅ (Phase 4.6 — this PR)

Still to come:

6. **Phase 4.7: libopenvizsla device selection by serial.** Upstream C
   patch (or a libftdi-level wrapper) so `StartRequest.device_serial` gets
   honored. UI + REST contract are already forward-compat.
7. **Phase 5: Claude tool-use analysis.** `ovweb.analyze.*` runs the five
   tools described below against a closed session, produces a markdown
   report + driver skeleton.
8. **Phase 6: quadlets + compose-dev.yml.** Rootless `systemd --user`
   auto-start via podman quadlets; `compose-dev.yml` for ad-hoc
   multi-container dev.

## Local dev workflow

- Python: `uv` for env + deps. Lockfile committed.
- Frontend: `pnpm`. Built output **not** committed; built in CI / Containerfile multi-stage.
- Tests: `pytest` for backend, `vitest` for frontend. Real pcap fixtures in `tests/fixtures/` (small, < 1 MB each).
- Linting: `ruff` + `ruff format` for Python, `eslint` + `prettier` for TS. CI fails on warnings.
- Pre-commit hook runs ruff and eslint; do not skip.

## Out of scope (be explicit; do not drift)

- USB 3.x / SuperSpeed capture (hardware cannot do it).
- USB/IP or any remote device passthrough.
- Non-Anthropic LLM backends.
- Multi-board / concurrent capture sessions on one host.
- Authentication / multi-user. The web UI assumes a single trusted operator behind whatever reverse proxy or VPN the deployer chooses.
- Cross-platform packaging. Linux + Podman only.
