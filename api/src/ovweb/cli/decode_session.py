"""`decode-session` CLI: raw.pcap -> session.sqlite.

Standalone Phase-3 tool. No HTTP, no UI, no live capture.

Pipeline:
  tshark -T fields         -> UsbLinkPacket stream
  reassembly FSM           -> Transfer stream
  SQLite bulk writer       -> transfers + endpoints rows (WAL mode)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ovweb.db import open_db
from ovweb.ingest.reassembly import Transfer, reassemble
from ovweb.ingest.tshark import stream_packets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="decode-session",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("pcap", help="path to the raw pcap file")
    ap.add_argument("--out",
                    help="output sqlite path (default: alongside pcap, .sqlite suffix)")
    ap.add_argument("--speed", choices=["ls", "fs", "hs", "unknown"],
                    default="unknown", help="bus speed recorded on the session row")
    ap.add_argument("--notes", default=None)
    ap.add_argument("--include-sofs", action="store_true",
                    help="ingest SOFs too (debug only; 99%% of HS by count)")
    args = ap.parse_args(argv)

    pcap_path = Path(args.pcap).resolve()
    if not pcap_path.exists():
        print(f"error: {pcap_path} does not exist", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else pcap_path.with_suffix(".sqlite")

    t0 = time.monotonic()
    con = open_db(out_path)
    session_id = _create_session(con, pcap_path, args.speed, args.notes)

    n_transfers = 0
    summary: dict[tuple[int, int], _EpStats] = defaultdict(_EpStats)

    # Single tshark pass. Count packets inline, feed reassembly on the fly.
    raw_packets = stream_packets(str(pcap_path), include_sofs=False)
    n_packets_seen = [0]

    def _tee(it):
        for p in it:
            n_packets_seen[0] += 1
            yield p

    with con:  # transaction
        for transfer in reassemble(_tee(raw_packets)):
            _insert_transfer(con, session_id, transfer)
            n_transfers += 1
            ep = (transfer.device_addr, transfer.endpoint)
            summary[ep].observe(transfer)

        _write_endpoint_summaries(con, session_id, summary)
        con.execute(
            "UPDATE sessions SET ended_at = ?, status = 'closed' WHERE id = ?",
            (_utcnow_iso(), session_id),
        )

    dt = time.monotonic() - t0
    print(f"session_id={session_id}  pcap={pcap_path}")
    print(f"  packets read : {n_packets_seen[0]}")
    print(f"  transfers    : {n_transfers}")
    print(f"  elapsed      : {dt:.2f}s")
    _print_endpoint_table(summary)
    return 0


# --- session / transfer writers -----------------------------------------


def _create_session(
    con: sqlite3.Connection, pcap_path: Path, speed: str, notes: str | None,
) -> int:
    started = datetime.fromtimestamp(pcap_path.stat().st_mtime, tz=UTC).isoformat()
    cur = con.execute(
        "INSERT INTO sessions (started_at, status, speed, notes, source_pcap) "
        "VALUES (?, 'live', ?, ?, ?)",
        (started, speed, notes, str(pcap_path)),
    )
    return int(cur.lastrowid)


def _insert_transfer(
    con: sqlite3.Connection, session_id: int, t: Transfer,
) -> None:
    length = len(t.data_bytes) + (8 if t.setup_bytes else 0)
    con.execute(
        "INSERT INTO transfers "
        "(session_id, ts_ns, ep_addr, device_addr, direction, type, "
        "setup_bytes, data_bytes, length, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, t.ts_ns, t.endpoint, t.device_addr,
         t.direction, t.type,
         t.setup_bytes or None, t.data_bytes or None,
         length, t.status),
    )


def _write_endpoint_summaries(
    con: sqlite3.Connection, session_id: int,
    summary: dict[tuple[int, int], "_EpStats"],
) -> None:
    for (addr, ep), stats in sorted(summary.items()):
        con.execute(
            "INSERT OR REPLACE INTO endpoints "
            "(session_id, device_addr, ep_addr, type, mps, observed_summary_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, addr, ep, stats.xfer_type, stats.max_data_len,
             json.dumps(stats.to_json(), sort_keys=True)),
        )


# --- per-endpoint running stats -----------------------------------------


@dataclass(slots=True)
class _EpStats:
    n_in: int = 0
    n_out: int = 0
    n_setup: int = 0
    n_ack: int = 0
    n_nak: int = 0
    n_stall: int = 0
    n_nyet: int = 0
    n_incomplete: int = 0
    max_data_len: int = 0
    xfer_type: str | None = None  # 'control' is set when we see a SETUP

    def observe(self, t: Transfer) -> None:
        if t.direction == "in":
            self.n_in += 1
        elif t.direction == "out":
            self.n_out += 1
        elif t.direction == "setup":
            self.n_setup += 1
            self.xfer_type = "control"
        counter = {
            "ack": "n_ack", "nak": "n_nak", "stall": "n_stall",
            "nyet": "n_nyet", "incomplete": "n_incomplete",
        }.get(t.status)
        if counter:
            setattr(self, counter, getattr(self, counter) + 1)
        n = len(t.data_bytes)
        if n > self.max_data_len:
            self.max_data_len = n
        if self.xfer_type is None and t.type != "unknown":
            self.xfer_type = t.type

    def to_json(self) -> dict:
        return {
            "in": self.n_in, "out": self.n_out, "setup": self.n_setup,
            "ack": self.n_ack, "nak": self.n_nak, "stall": self.n_stall,
            "nyet": self.n_nyet, "incomplete": self.n_incomplete,
            "max_data_len": self.max_data_len,
        }


# --- helpers -------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _print_endpoint_table(summary: dict[tuple[int, int], _EpStats]) -> None:
    if not summary:
        print("  (no endpoints observed)")
        return
    print(f"  {'dev.ep':>8} {'type':>18} {'in':>6} {'out':>6} {'setup':>6} "
          f"{'ack':>6} {'nak':>6} {'stall':>5} {'maxlen':>6}")
    for (addr, ep), s in sorted(summary.items()):
        print(f"  {addr:>3}.{ep:<4} {(s.xfer_type or '?'):>18} "
              f"{s.n_in:>6} {s.n_out:>6} {s.n_setup:>6} "
              f"{s.n_ack:>6} {s.n_nak:>6} {s.n_stall:>5} "
              f"{s.max_data_len:>6}")


if __name__ == "__main__":
    sys.exit(main())
