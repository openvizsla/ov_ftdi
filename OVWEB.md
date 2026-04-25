# ovweb — OpenVizsla 3 web UI

Self-hosted web UI for the [OpenVizsla 3.2](https://www.crowdsupply.com/nycresistor/openvizsla-ov3) USB
protocol analyzer. Captures USB 1.1 / 2.0 (Low / Full / High speed) traffic
from the OV3 tap, decodes it with `tshark`, stores every transfer in SQLite,
and serves a live three-channel feed to a Svelte frontend: a live endpoint
summary (the useful, low-cardinality view), a filtered event stream
(descriptors, control transfers, payload changes, status flips), and an
opt-in raw firehose behind a collapsed pane.

One rootless Podman container owns everything: the FTDI, libopenvizsla, the
FastAPI + WebSocket server, and the UI. Device selection happens from the
browser.

```
  OV3 hardware (FT2232H)
           │  USB
           ▼
  ovweb-api  ─────── http://127.0.0.1:8000  ◄── browser
```

Claude-assisted protocol analysis is on the roadmap (Phase 5) but not shipped
yet. For design rationale, hardware context and known carve-outs see
[CLAUDE.md](CLAUDE.md).

## Prerequisites

Fedora / RHEL host (SELinux enforcing is fine), rootless Podman 4.4 or newer,
an OV3 board plugged into USB. No host-side Python, Node, tshark, or pnpm
needed — everything runs in the container.

Verify Podman:

```sh
podman --version          # >= 4.4
loginctl show-user "$(whoami)" | grep Linger   # optional: keeps user services
```

### udev rule (one-time, per host)

The container runs rootless, so the USB device node must be user-accessible
via the `uaccess` udev tag.

```sh
sudo cp udev/52-openvizsla.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger
# Then *physically* unplug and replug the OV3 — udev only re-tags on bind.
```

Verify:

```sh
lsusb | grep -E '1d50:607c|0403:6010'   # OV3 EEPROM or raw FTDI fallback
```

If nothing shows up, the board isn't enumerating. If it shows up but ovweb
reports "ov_open failed: unable to claim usb device", the udev rule wasn't
reloaded or the board wasn't replugged since installing it.

## Build and run

```sh
api/build-image.sh     # ~5 min first time: compiles libopenvizsla + Svelte
                       #                    + Python deps (cached on rebuild)
api/run.sh             # starts ovweb, attaches, publishes 127.0.0.1:8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The container stays
attached; Ctrl-C stops it cleanly.

`api/run.sh` bind-mounts `/dev/bus/usb` read-write (so the supervisor can
open the FTDI) and disables SELinux confinement (`container_t` cannot touch
`usb_device_t` by default). It also warns if no OV3 is detected at start-up,
but does not refuse to run — you can plug one in after the UI is up and
click "Rescan".

## Using the UI

1. **Device** — dropdown lists every attached FT2232H. Auto-selected when
   there's exactly one. If more than one is plugged in, a banner warns that
   libopenvizsla 4.6 always opens the first match; serial-based selection
   lands in Phase 4.7.
2. **Rescan** — requery `GET /api/devices`. Use this after plugging a board
   in with ovweb already running.
3. **Speed** — `ls` (1.5 Mbps), `fs` (12 Mbps), `hs` (480 Mbps). Pick
   explicitly. Auto-detect is deliberately disabled — the current
   libopenvizsla wedges if an HS probe has to step down to FS/LS on the
   same session. See CLAUDE.md "libopenvizsla HS→FS→LS probe wedging".
4. **Start capture** — opens the device, probes the selected speed, locks
   as soon as the PHY sync signal is seen, then begins the live feed.
5. **Endpoints** (primary pane) — one live-updating row per `device.ep`.
   Count, bytes, ack / nak / stall mix, current run-length, last payload.
   Updated every 250 ms; never scrolls.
6. **Events** (middle pane) — filtered event feed. Expect `speed_locked`,
   `new_endpoint` as endpoints come online, `control_transfer` during
   enumeration (descriptors, configuration, class-specific setup), and then
   `payload_change` entries when interrupt-IN endpoints actually produce
   new data. Run-of-NAK and STALL flips surface as `status_flip`.
7. **Raw firehose** — collapsed `<details>`. Expand to subscribe to every
   transfer (the old full table). Collapse to unsubscribe; the server stops
   pushing those events for your session.
8. **Stop capture** — ends the session, releases the FTDI, rebuilds the
   endpoint summary for the stored detail view.

Every transfer goes into `/data/ovweb.sqlite` regardless of which UI channels
you're subscribed to — the filter only affects what's streamed over the
WebSocket.

## Data locations

| Data              | Default path                        | Overridable via   |
|-------------------|-------------------------------------|-------------------|
| Session DB        | `~/.local/share/ovweb/ovweb.sqlite` | `OV_DATA_DIR`     |
| UI port (host)    | `127.0.0.1:8000`                    | `OV_PORT`         |
| Image tag         | `ovweb-api:latest`                  | `IMAGE_NAME`      |

The SQLite DB is opened in WAL mode, so `ovweb.sqlite-wal` and
`ovweb.sqlite-shm` sidecar files appear next to it — leave them alone.

## Troubleshooting

- **`lsusb` shows the OV3 but ovweb prints "ov_open failed: unable to
  claim usb device"** — another process has the FTDI claimed (stale
  ov-capture / ovweb container from a previous run, or the kernel's
  `ftdi_sio` driver bound to it). `podman ps -a | grep ov-` and `podman
  stop` any leftovers; for `ftdi_sio`, the udev rule should prevent it
  from binding, so the usual fix is the reload-and-replug step above.
- **`/api/devices` returns `[]` but `lsusb` shows the board** —
  `/dev/bus/usb` wasn't bind-mounted, or `--security-opt label=disable`
  was dropped. Both come from `api/run.sh`; check that you're using it
  unmodified.
- **"no OpenVizsla 3 attached" on start** — plug one in and hit Rescan;
  no container restart needed.
- **Events pane shows "speed_locked" but no endpoints ever appear** —
  device is idle or the target side of J2/J3 isn't wired to anything.
  Expand the Raw firehose to sanity-check that ANY frames are arriving.
- **tshark version drift breaks JSON** — pinned at bookworm 4.0.x in the
  Containerfile; do not override.

## Developing without containers

See the "Dev loop" section of [CLAUDE.md](CLAUDE.md) for a host-native
workflow: `uv sync` in `api/`, `pnpm dev` in `frontend/` with Vite
proxying `/api` → `:8000`. Host-side you need `tshark` + `libopenvizsla` +
`libftdi1` + `libusb-1.0` installed, and the udev rule applied.

`pnpm build` in `frontend/` writes directly into `api/src/ovweb/ui/` — that
committed tree is purely for host-side `uvicorn` runs. The container
reproduces the UI from source on every build (via the `.containerignore`
exclude) so a stale committed UI can never leak into the image.

## What's next

- **Phase 4.7** — libopenvizsla patch (or wrapper) that honors a
  `device_serial` selector so the dropdown can actually drive the pick
  when multiple OV3s are attached. The REST / UI contract is already
  forward-compat: `POST /api/sessions` accepts `device_serial` today,
  it's just ignored by the supervisor.
- **Phase 5** — Claude tool-use analysis worker (`ovweb.analyze.*`): given
  a closed session, produce a markdown protocol report plus a pyusb /
  hidapi / libuvc skeleton. Design in CLAUDE.md, code not yet written.
- **Phase 6** — `quadlets/` directory with `.container` units for rootless
  systemd `--user` auto-start.

## License / provenance

Gateware and hardware design from [openvizsla/ov_ftdi](https://github.com/openvizsla/ov_ftdi).
libopenvizsla from [matwey/libopenvizsla](https://github.com/matwey/libopenvizsla).
Everything new in this repo (supervisor, ovweb API, UI, container glue) is
project-local.
