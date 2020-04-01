#!/usr/bin/env python3

# This needs python3.3 or greater - argparse changes behavior
# TODO - workaround

import LibOV
import argparse
import time

import zipfile

import sys
import os, os.path
import struct
#import yappi

# We check the Python version in __main__ so we don't
#   rudely bail if someone imports this module.
MIN_MAJOR = 3
MIN_MINOR = 3

default_package = os.getenv('OV_PKG')
if default_package is None:
    default_package = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ov3.fwpkg")

def as_ascii(arg):
    if arg == None:
        return None
    return arg.encode('ascii')

class Command:
    def __subclasshook__(self):
        pass

    @staticmethod
    def setup_args(sp):
        pass

__cmd_keeper = []
def command(_name, _help, *_args):
    def _i(todeco):
        class _sub(Command):
            name = _name
            help = _help

            @staticmethod
            def setup_args(sp):
                for (name, typ, *default) in _args:
                    if len(default):
                            name = "--" + name
                            default = default[0]
                    else:
                        default = None
                    sp.add_argument(name, type=typ, default=default)

            @staticmethod
            def go(dev, args):
                aarray = dict([(i, getattr(args, i)) for (i, *_) in _args])
                todeco(dev, **aarray)
        __cmd_keeper.append(_sub)
        return todeco

    return _i

int16 = lambda x: int(x, 16)


def check_ulpi_clk(dev):
    clks_up = dev.regs.ucfg_stat.rd()

    if not clks_up:
        print("ULPI Clock has not started up - osc?")
        return 1

    return 0

@command('uwrite', 'Write ULPI Register', ('addr', str), ('val', int16))
def uwrite(dev, addr, val):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    dev.ulpiwrite(addr, val)

@command('uread', 'Read ULPI Register', ('addr', str))
def uread(dev, addr):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    print ("ULPI %02x: %02x" % (addr, dev.ulpiread(addr)))

@command('report', 'Hardware Health Report')
def report(dev):

    print("USB PHY Tests")
    if check_ulpi_clk(dev):
        print("\tWARNING: ULPI PHY clock not started; skipping ULPI tests")
    else:
        # display the ULPI identifier
        ident = 0
        for x in [dev.ulpiregs.vidh,
                dev.ulpiregs.vidl,
                dev.ulpiregs.pidh,
                dev.ulpiregs.pidl]:
            ident <<= 8
            ident |= x.rd()

        name = 'unknown'
        if ident == LibOV.SMSC_334x_MAGIC:
            name = 'SMSC 334x'
        print("\tULPI PHY ID: %08x (%s)" % (ident, name))

        # do in depth phy tests
        if ident == LibOV.SMSC_334x_MAGIC:
            dev.ulpiregs.scratch.wr(0)
            dev.ulpiregs.scratch_set.wr(0xCF)
            dev.ulpiregs.scratch_clr.wr(0x3C)

            stat = "OK" if dev.ulpiregs.scratch.rd() == 0xC3 else "FAIL"

            print("\tULPI Scratch register IO test: %s" % stat)
            print("\tPHY Function Control Reg:  %02x" % dev.ulpiregs.func_ctl.rd())
            print("\tPHY Interface Control Reg: %02x" % dev.ulpiregs.intf_ctl.rd())
        else:
            print("\tUnknown PHY - skipping phy tests")

    print ("SDRAM tests")
    def cb(n, ok):
        print("\t... %d: %s" % (n, "OK" if ok else "FAIL"))
    stat = do_sdramtests(dev, cb)
    if stat == -1:
        print("\t... all passed")


class OutputCustom:
    def __init__(self, output, speed):
        self.output = output
        self.speed = speed
        self.last_ts = 0
        self.ts_offset = 0
        try:
            with open("template_custom.txt") as f:
                self.template = f.readline()
        except:
            self.template = "data=%s speed=%s time=%f\n"

    def handle_usb(self, ts, pkt, flags):
        if ts < self.last_ts:
            self.ts_offset += 0x1000000
        self.last_ts = ts
        pkthex = " ".join("%02x" % x for x in pkt)
        self.output.write(bytes(self.template % (pkthex, self.speed.upper(), (ts + self.ts_offset) / 60e6), "ascii"))


class OutputITI1480A:
    def __init__(self, output, speed):
        self.output = output
        self.speed = speed
        self.ts_offset = 0
        self.ts_last = None

    def handle_usb(self, ts, pkt, flags):
        buf = []

        # Skip SOF and empty packets
        if (len(pkt) == 0) or (pkt[0] == 0xa5):
            return

        # Normalize timestamp and get delta vs prev packet
        if self.ts_last is None:
            self.ts_last = ts

        if ts < self.ts_last:
            self.ts_offset

        ts_delta = ts - self.ts_last

        self.ts_last = ts

        # Prepare data
        buf = bytearray(4 + 2 + 2*len(pkt) + 2)

        # Write timestamp delta
        buf[0] = (ts_delta & 0x0000ff0) >> 4
        buf[1] = (ts_delta & 0x000000f) | 0x30
        buf[2] = (ts_delta & 0xff00000) >> 20
        buf[3] = (ts_delta & 0x00ff000) >> 12

        # Write packet start
        buf[4] = 0x40
        buf[5] = 0xc0

        # Write packet data
        buf[6:-2:2] = pkt
        buf[7:-2:2] = b'\x80' * len(pkt)

        # Write packet end
        buf[-2] = 0x00
        buf[-1] = 0xc0

        # To file
        self.output.write(buf)


class OutputPcap:
    LINKTYPE_USB_2_0 = 288

    def __init__(self, output):
        self.output = output
        self.output.write(struct.pack("IHHIIII", 0xa1b23c4d, 2, 4, 0, 0, 65535, self.LINKTYPE_USB_2_0))
        # Assume that capture started at the same time this object was created. This is not a proper time
        # synchronization but should be good enough. Record time is advanced based on the FPGA clock.
        self.utc_ts = int(time.time())
        self.last_ts = 0
        self.ts_offset = 0

    def handle_usb(self, ts, pkt, flags):
        # Increment timestamp based on the 60 MHz 24-bit counter value.
        # Convert remaining clocks to nanoseconds: 1 clk = 1 / 60 MHz = 16.(6) ns
        if ts < self.last_ts:
            self.ts_offset += (1 << 24)
        self.last_ts = ts
        clks = self.ts_offset + ts
        if clks >= 60e6:
            self.utc_ts += 1
            self.ts_offset -= 60e6
            clks -= 60e6
        nanosec = int((clks * 17) - (clks // 3))
        if len(pkt) == 0:
            return
        # Write pcap record header in host endian
        # TODO: FPGA does not provide us with the untruncated packet length thus incl_len is set to orig_len
        # When (and if) FPGA does indicate the length of truncated packets, change the record header to
        # contain different incl_len (len(pkt)) and orig_len (untruncated packet size)
        self.output.write(struct.pack("IIII", self.utc_ts, nanosec, len(pkt), len(pkt)))
        # Write USB packet, beginning with a PID as it appeared on the bus
        self.output.write(pkt)


def do_sdramtests(dev, cb=None, tests = range(0, 6)):

    for i in tests:
        dev.regs.SDRAM_TEST_CMD.wr(0x80 | i)
        stat = 0x40
        while (stat & 0x40):
            time.sleep(0.1)
            stat = dev.regs.SDRAM_TEST_CMD.rd() 

        ok = stat & 0x20
        if cb is not None:
            cb(i, ok)

        if not ok:
            return i
    else:
        return -1

@command('sdramtest', 'Perform SDRAM Test')
def sdramtest(dev):
    # LEDS select
    dev.regs.LEDS_MUX_0.wr(1)

    stat = do_sdramtests(dev, tests = [3])
    if stat != -1:
        print("SDRAM test failed on test %d\n" % stat)
    else:
        print("SDRAM test passed")

    dev.regs.LEDS_MUX_0.wr(0)

sniff_speeds = ["hs", "fs", "ls"]
sniff_formats = ["verbose", "custom", "pcap", "iti1480a"]

def do_sniff(dev, speed, format, out, timeout):
    # LEDs off
    dev.regs.LEDS_MUX_2.wr(0)
    dev.regs.LEDS_OUT.wr(0)

    # LEDS 0/1 to FTDI TX/RX
    dev.regs.LEDS_MUX_0.wr(2)
    dev.regs.LEDS_MUX_1.wr(2)

    # enable SDRAM buffering
    ring_base = 0
    ring_size = 16 * 1024 * 1024
    ring_end = ring_base + ring_size
    dev.regs.SDRAM_SINK_GO.wr(0)
    dev.regs.SDRAM_HOST_READ_GO.wr(0)
    dev.regs.SDRAM_SINK_RING_BASE.wr(ring_base)
    dev.regs.SDRAM_SINK_RING_END.wr(ring_end)
    dev.regs.SDRAM_HOST_READ_RING_BASE.wr(ring_base)
    dev.regs.SDRAM_HOST_READ_RING_END.wr(ring_end)
    dev.regs.SDRAM_SINK_GO.wr(1)
    dev.regs.SDRAM_HOST_READ_GO.wr(1)

    # clear perfcounters
    dev.regs.OVF_INSERT_CTL.wr(1)
    dev.regs.OVF_INSERT_CTL.wr(0)

    assert speed in sniff_speeds

    if check_ulpi_clk(dev):
        return

    # set to non-drive; set FS or HS as requested
    if speed == "hs":
            dev.ulpiregs.func_ctl.wr(0x48)
            dev.rxcsniff.service.highspeed = True
    elif speed == "fs":
            dev.ulpiregs.func_ctl.wr(0x49)
            dev.rxcsniff.service.highspeed = False
    elif speed == "ls":
            dev.ulpiregs.func_ctl.wr(0x4a)
            dev.rxcsniff.service.highspeed = False
    else:
        assert 0,"Invalid Speed"

    assert format in sniff_formats

    output_handler = None
    out = out and open(out, "wb")

    if format == "custom":
        output_handler = OutputCustom(out or sys.stdout, speed)
    elif format == "pcap":
        assert out, "can't output pcap to stdout, use --out"
        output_handler = OutputPcap(out)
    elif format == "iti1480a":
        output_handler = OutputITI1480A(out, speed)

    if output_handler is not None:
      dev.rxcsniff.service.handlers = [output_handler.handle_usb]

    elapsed_time = 0
    try:
        dev.regs.CSTREAM_CFG.wr(1)
        while 1:
            dev.regs.SDRAM_SINK_PTR_READ.wr(0)
            dev.regs.OVF_INSERT_CTL.wr(0)

            rptr = dev.regs.SDRAM_SINK_RPTR.rd()
            wptr = dev.regs.SDRAM_SINK_WPTR.rd()
            wrap_count = dev.regs.SDRAM_SINK_WRAP_COUNT.rd()

            rptr -= ring_base
            wptr -= ring_base

            assert 0 <= rptr <= ring_size
            assert 0 <= wptr <= ring_size

            delta = wptr - rptr
            if delta < 0:
                delta += ring_size

            total = wrap_count * ring_size + wptr
            utilization = delta * 100 / ring_size

            print("%d / %d (%3.2f %% utilization) %d kB | %d overflow, %08x total | R%08x W%08x" %
                (delta, ring_size, utilization, total / 1024,
                dev.regs.OVF_INSERT_NUM_OVF.rd(), dev.regs.OVF_INSERT_NUM_TOTAL.rd(),
                rptr, wptr
                ), file = sys.stderr)

            dev.regs.OVF_INSERT_CTL.wr(0)
            print("%d overflow, %08x total" % (dev.regs.OVF_INSERT_NUM_OVF.rd(), dev.regs.OVF_INSERT_NUM_TOTAL.rd()), file = sys.stderr)

            if False:
                dev.regs.SDRAM_SINK_DEBUG_CTL.wr(0)
                print("rptr = %08x i_stb=%08x i_ack=%08x d_stb=%08x d_term=%08x s0=%08x s1=%08x s2=%08x | wptr = %08x i_stb=%08x i_ack=%08x d_stb=%08x d_term=%08x s0=%08x s1=%08x s2=%08x wrap=%x" % (
                    dev.regs.SDRAM_HOST_READ_RPTR_STATUS.rd(),
                    dev.regs.SDRAM_HOST_READ_DEBUG_I_STB.rd(),
                    dev.regs.SDRAM_HOST_READ_DEBUG_I_ACK.rd(),
                    dev.regs.SDRAM_HOST_READ_DEBUG_D_STB.rd(),
                    dev.regs.SDRAM_HOST_READ_DEBUG_D_TERM.rd(),
                    dev.regs.SDRAM_HOST_READ_DEBUG_S0.rd(),
                    dev.regs.SDRAM_HOST_READ_DEBUG_S1.rd(),
                    dev.regs.SDRAM_HOST_READ_DEBUG_S2.rd(),
                    dev.regs.SDRAM_SINK_WPTR.rd(),
                    dev.regs.SDRAM_SINK_DEBUG_I_STB.rd(),
                    dev.regs.SDRAM_SINK_DEBUG_I_ACK.rd(),
                    dev.regs.SDRAM_SINK_DEBUG_D_STB.rd(),
                    dev.regs.SDRAM_SINK_DEBUG_D_TERM.rd(),
                    dev.regs.SDRAM_SINK_DEBUG_S0.rd(),
                    dev.regs.SDRAM_SINK_DEBUG_S1.rd(),
                    dev.regs.SDRAM_SINK_DEBUG_S2.rd(),
                    dev.regs.SDRAM_SINK_WRAP_COUNT.rd(),
                    ), file = sys.stderr)
            if timeout and elapsed_time > timeout:
                break
            time.sleep(1)
            elapsed_time = elapsed_time + 1
    except KeyboardInterrupt:
        pass
    finally:
        dev.regs.SDRAM_SINK_GO.wr(0)
        dev.regs.SDRAM_HOST_READ_GO.wr(0)
        dev.regs.CSTREAM_CFG.wr(0)

    if out is not None:
        out.close()

class Sniff(Command):
    name = "sniff"
    help = 'Perform USB trace / sniffing'

    @staticmethod
    def setup_args(sp):
        #@command('sniff', ('speed', str,), ('format', str, 'verbose', formats), ('out', str, None), ('timeout', int, None))
        sp.add_argument('speed', type=str, choices=sniff_speeds,
                        help='USB Speed (High Speed, Full Speed, Low Speed)')
        sp.add_argument('--format', type=str, default='verbose', choices=sniff_formats,
                        help='Output file format')
        sp.add_argument('--out', type=str,
                        help='Output file name')
        sp.add_argument('--timeout', type=int, help='Timeout in seconds')

    @staticmethod
    def go(dev, args):
        do_sniff(dev, args.speed, args.format, args.out, args.timeout)


@command('debug-stream', 'Debug Stream')
def debug_stream(dev):
    cons = dev.regs.CSTREAM_CONS_LO.rd() | dev.regs.CSTREAM_CONS_HI.rd() << 8
    prod_hd = dev.regs.CSTREAM_PROD_HD_LO.rd() | dev.regs.CSTREAM_PROD_HD_HI.rd() << 8
    prod = dev.regs.CSTREAM_PROD_LO.rd() | dev.regs.CSTREAM_PROD_HI.rd() << 8
    size = dev.regs.CSTREAM_SIZE_LO.rd() | dev.regs.CSTREAM_SIZE_HI.rd() << 8

    state = dev.regs.CSTREAM_PROD_STATE.rd()

    laststart = dev.regs.CSTREAM_LAST_START_LO.rd() | dev.regs.CSTREAM_LAST_START_HI.rd() << 8
    lastcount = dev.regs.CSTREAM_LAST_COUNT_LO.rd() | dev.regs.CSTREAM_LAST_COUNT_HI.rd() << 8
    lastpw = dev.regs.CSTREAM_LAST_PW_LO.rd() | dev.regs.CSTREAM_LAST_PW_HI.rd() << 8

    print("cons: %04x prod-wr: %04x prod-hd: %04x size: %04x state: %02x" % (cons, prod, prod_hd, size, state))
    print("\tlaststart: %04x lastcount: %04x (end: %04x) pw-at-write: %04x" % (laststart, lastcount, laststart + lastcount, lastpw))

@command('ioread', 'Read I/O', ('addr', str))
def ioread(dev, addr):
    print("%s: %02x" % (addr, dev.ioread(addr)))

@command('iowrite', 'Write I/O', ('addr', str), ('value', int16))
def iowrite(dev, addr, value):
    dev.iowrite(addr, value)

@command('led-test', 'Test LEDs', ('v', int16))
def ledtest(dev, v):
    dev.regs.leds_out.wr(v)

@command('eep-erase', 'Erase EEPROM')
def eeperase(dev):
    dev.dev.eeprom_erase()

@command('eep-program', 'Write EEPROM', ('serialno', int))
def eepprogram(dev, serialno):
    dev.dev.eeprom_program(serialno)

@command('sdram_host_read_test', 'Test SDRAM reading from host')
def sdram_host_read_test(dev):

    ring_base = 0x10000
    ring_end = ring_base + 1024*1024

    dev.regs.SDRAM_SINK_RING_BASE.wr(ring_base)
    dev.regs.SDRAM_SINK_RING_END.wr(ring_end)

    dev.regs.SDRAM_HOST_READ_RING_BASE.wr(ring_base)
    dev.regs.SDRAM_HOST_READ_RING_END.wr(ring_end)

    cnt = 0
    while True:
        rptr = dev.regs.SDRAM_HOST_READ_RPTR_STATUS.rd()
        cnt += 1
        if cnt == 5:
            print("GO SINK")
            dev.regs.SDRAM_SINK_GO.wr(1)
        if cnt == 10:
            print("GO SOURCE")
            dev.regs.SDRAM_HOST_READ_GO.wr(1)

        print("rptr = %08x i_stb=%08x i_ack=%08x d_stb=%08x d_term=%08x s0=%08x s1=%08x s2=%08x | wptr = %08x i_stb=%08x i_ack=%08x d_stb=%08x d_term=%08x s0=%08x s1=%08x s2=%08x wrap=%x" % (
            rptr,
            dev.regs.SDRAM_HOST_READ_DEBUG_I_STB.rd(),
            dev.regs.SDRAM_HOST_READ_DEBUG_I_ACK.rd(),
            dev.regs.SDRAM_HOST_READ_DEBUG_D_STB.rd(),
            dev.regs.SDRAM_HOST_READ_DEBUG_D_TERM.rd(),
            dev.regs.SDRAM_HOST_READ_DEBUG_S0.rd(),
            dev.regs.SDRAM_HOST_READ_DEBUG_S1.rd(),
            dev.regs.SDRAM_HOST_READ_DEBUG_S2.rd(),
            dev.regs.SDRAM_SINK_WPTR.rd(),
            dev.regs.SDRAM_SINK_DEBUG_I_STB.rd(),
            dev.regs.SDRAM_SINK_DEBUG_I_ACK.rd(),
            dev.regs.SDRAM_SINK_DEBUG_D_STB.rd(),
            dev.regs.SDRAM_SINK_DEBUG_D_TERM.rd(),
            dev.regs.SDRAM_SINK_DEBUG_S0.rd(),
            dev.regs.SDRAM_SINK_DEBUG_S1.rd(),
            dev.regs.SDRAM_SINK_DEBUG_S2.rd(),
            dev.regs.SDRAM_SINK_WRAP_COUNT.rd(),
            ), file = sys.stderr)

        if cnt == 20:
            print("STOP")
            dev.regs.SDRAM_HOST_READ_GO.wr(0)
#            print("STOP: %d" % dev.regs.SDRAM_HOST_READ_GO.rd())


class LB_Test(Command):
    name = "lb-test"
    help = ''

    @staticmethod
    def setup_args(sp):
        sp.add_argument("size", type=int, default=64, nargs='?')

    @staticmethod
    def go(dev, args):
        # Stop the generator - do twice to make sure
        # theres no hanging packet 
        dev.regs.RANDTEST_CFG.wr(0)
        dev.regs.RANDTEST_CFG.wr(0)

        # LEDs off
        dev.regs.LEDS_MUX_2.wr(0)
        dev.regs.LEDS_OUT.wr(0)

        # LEDS 0/1 to FTDI TX/RX
        dev.regs.LEDS_MUX_0.wr(2)
        dev.regs.LEDS_MUX_1.wr(2)

        # Set test packet size
        dev.regs.RANDTEST_SIZE.wr(args.size)

        # Reset the statistics counters
        dev.lfsrtest.reset()

        # Start the test (and reinit the generator)
        dev.regs.RANDTEST_CFG.wr(1)

        st = time.time()
        try:
            while 1:
                time.sleep(1)
                b = dev.lfsrtest.stats()
                print("%4s %20d bytes %f MB/sec average" % (
                    "ERR" if b.error else "OK", 
                    b.total, b.total/float(time.time() - st)/1024/1024))

        except KeyboardInterrupt:
            dev.regs.randtest_cfg.wr(0)


def min_version_check(major, minor):
    error_msg = 'ERROR: I depend on behavior in Python {0}.{1} or greater'
    if sys.version_info < (major, minor):
        sys.exit(error_msg.format(major, minor))


def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", "-p", type=lambda x: zipfile.ZipFile(x, 'r'), 
            default=default_package)
    ap.add_argument("-l", "--load", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--config-only", "-C", action="store_true")

    # Bind commands
    subparsers = ap.add_subparsers(title='subcommands',
                                   description='Supported Sub-commands, each has their own --help')
    for i in Command.__subclasses__():
        sp = subparsers.add_parser(i.name, help=i.help)
        i.setup_args(sp)
        sp.set_defaults(hdlr=i)

    args = ap.parse_args()


    dev = LibOV.OVDevice(mapfile=args.pkg.open('map.txt', 'r'), verbose=args.verbose)

    err = dev.open(bitstream=args.pkg.open('ov3.bit', 'r') if args.load else None)

    if err:
        if err == -4:
            print("USB: Unable to find device")
            return 1
        print("USB: Error opening device (1)\n")
        print(err)

    if not dev.isLoaded():
        print("FPGA not loaded, forcing reload")
        dev.close()

        err = dev.open(bitstream=args.pkg.open('ov3.bit','r'))

    if err:
        print("USB: Error opening device (2)\n")
        return 1


    if args.config_only:
        return

    if not (hasattr(args, 'hdlr') and args.hdlr.name.startswith("eep-")):
        ret = dev.dev.eeprom_sanitycheck()
        if ret > 0:
            print("\nPlease run this tool with the subcommand 'eep-program <serial number>'")
            print("to program your EEPROM. The FT2232H FIFO will not work correctly with")
            print("default settings.")
            return 1
        elif ret < 0:
            print("USB: Error checking EEPROM\n")
            return 1

    dev.dev.write(LibOV.FTDI_INTERFACE_A, b'\x00' * 512, async_=False)

    try:
        if hasattr(args, 'hdlr'):
            args.hdlr.go(dev, args)
    finally:
        dev.close()

if  __name__ == "__main__":
    min_version_check(MIN_MAJOR, MIN_MINOR)
#    yappi.start()
    main()
#    yappi.print_stats()

