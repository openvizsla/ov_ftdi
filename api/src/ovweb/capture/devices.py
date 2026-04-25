"""USB device enumeration for the UI device picker.

libopenvizsla's public API (`ov_new(firmware)` -> `cha_open()` ->
`ftdi_usb_open(OV_VENDOR, OV_PRODUCT)`) auto-opens the *first* FT2232H match
it finds. There is no hook today for picking by serial, port, or bus/dev —
that's tracked as a Phase 4.7 upstream patch.

What we CAN do from Python is enumerate every candidate on the host via
pyusb, so the UI can show the user which boards are attached, which one the
supervisor will grab, and whether they've wired two OV3s up at once (in which
case we warn-and-proceed; the "first match" is deterministic given libusb's
iteration order).

Vendor/product filter:
  (0x1d50, 0x607c)  — OpenMoko-branded EEPROM, as shipped by the Kickstarter
  (0x0403, 0x6010)  — raw FTDI FT2232H (fallback; blank/wrong EEPROM)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


OV3_IDS: tuple[tuple[int, int], ...] = (
    (0x1d50, 0x607c),
    (0x0403, 0x6010),
)


@dataclass(slots=True)
class DeviceInfo:
    bus: int
    address: int
    port_path: str        # "1.2.3" — dot-joined libusb port_numbers
    serial: str | None
    vid: int
    pid: int
    description: str      # "OpenVizsla 3" | "Raw FTDI FT2232H"

    def to_dict(self) -> dict:
        return {
            "bus": self.bus,
            "address": self.address,
            "port_path": self.port_path,
            "serial": self.serial,
            "vid": self.vid,
            "pid": self.pid,
            "description": self.description,
        }


def _describe(vid: int, pid: int) -> str:
    if vid == 0x1d50 and pid == 0x607c:
        return "OpenVizsla 3"
    if vid == 0x0403 and pid == 0x6010:
        return "Raw FTDI FT2232H"
    return f"unknown {vid:04x}:{pid:04x}"


def enumerate() -> list[DeviceInfo]:
    """Return one `DeviceInfo` per attached OV3 candidate, sorted by
    (bus, port_path) for stable UI ordering.

    Reading the iSerialNumber string requires an OS-level handle to the
    device — rootless pyusb calls that go through to libusb's
    libusb_get_string_descriptor_ascii, which blocks (EACCES) if udev's
    uaccess tag hasn't applied for the invoking user. In that case we yield
    `serial=None` silently rather than failing the whole enumeration.
    """
    # Import inside the function so importing the ovweb package on a machine
    # without libusb (e.g. pure CI unit-tests) doesn't blow up.
    import usb.core
    import usb.util

    results: list[DeviceInfo] = []
    for vid, pid in OV3_IDS:
        for dev in usb.core.find(find_all=True, idVendor=vid, idProduct=pid) or []:
            try:
                port_numbers = getattr(dev, "port_numbers", None) or ()
                port_path = ".".join(str(p) for p in port_numbers)
                serial: str | None = None
                try:
                    if dev.iSerialNumber:
                        serial = usb.util.get_string(dev, dev.iSerialNumber)
                except Exception as e:  # noqa: BLE001
                    log.debug("serial read failed for %04x:%04x bus=%s: %s",
                              vid, pid, getattr(dev, "bus", "?"), e)
                results.append(DeviceInfo(
                    bus=int(dev.bus),
                    address=int(dev.address),
                    port_path=port_path,
                    serial=serial,
                    vid=vid,
                    pid=pid,
                    description=_describe(vid, pid),
                ))
            except Exception as e:  # noqa: BLE001
                log.warning("skipping device %04x:%04x: %s", vid, pid, e)

    results.sort(key=lambda d: (d.bus, d.port_path, d.address))
    return results
