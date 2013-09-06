#!/usr/bin/python3.3

# This needs python3.3 or greater - argparse changes behavior
# TODO - workaround

import LibOV
import argparse
import time

import zipfile

import sys
import os

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
def command(_name, *_args):
    def _i(todeco):
        class _sub(Command):
            name = _name

            @staticmethod
            def setup_args(sp):
                for (name, typ) in _args:
                    sp.add_argument(name, type=typ)

            @staticmethod
            def go(dev, args):
                aarray = dict([(i, getattr(args, i)) for (i, _) in _args])
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

@command('uwrite', ('addr', str), ('val', int16))
def uwrite(dev, addr, val):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    dev.ulpiwrite(addr, val)

@command('uread', ('addr', str))
def uread(dev, addr):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    print ("ULPI %02x: %02x" % (addr, dev.ulpiread(addr)))

@command('report')
def report(dev):

    print("USB PHY Tests")
    if check_ulpi_clk(dev):
        print("\tWARNING: ULPI PHY clock not started; skipping ULPI data")
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

@command('ioread', ('addr', str))
def ioread(dev, addr):
    print("%s: %02x" % (addr, dev.ioread(addr)))

@command('iowrite', ('addr', str), ('value', int16))
def iowrite(dev, addr, value):
    dev.iowrite(addr, value)

@command('led-test', ('v', int16))
def ledtest(dev, v):
    dev.regs.leds_out.wr(v)

class LB_Test(Command):
    name = "lb-test"

    @staticmethod
    def setup_args(sp):
        sp.add_argument("n", type=int, default=512000, nargs='?')

    @staticmethod
    def go(dev, args):
        b = bytes(i & 0xFF for i in range(args.n))


        class pp:
            def __init__(self, rc):
                self.nc = 0
                self.s = 0
                self.ok = True
                self.rc = 0
                self.goal = rc

            def __call__(self, buf, prog):
                if buf:
                    for i in buf:
                        if i != self.s:
                            print("mismatch! (%d %d)" % (i, self.s))
                            self.ok = False
                            self.s = i
                        self.s += 1
                        self.s &= 0xFF
                    self.rc += len(buf)
                self.nc += 1
                return 0 if self.rc < self.goal else  1

        PP = pp(args.n)

        print("Go! lb=%d" % len(b))
        rc = dev.write(LibOV.FTDI_INTERFACE_A, b, async=False)
        print("writeDone %s" % rc)
        sync = 1
        if sync:
            bb = dev.read(LibOV.FTDI_INTERFACE_A, args.n)
            print("Got %d bytes" % len(bb))
            PP(bb, None)
        else:
            dev.read_async(LibOV.FTDI_INTERFACE_A, PP, 4, 4)
            print("Got %d bytes" % PP.rc)
        print("FINI %s" % PP.ok)

def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", "-p", type=lambda x: zipfile.ZipFile(x, 'r'), 
            default=os.getenv('OV_PKG'))
    ap.add_argument("-l", "--load", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--config-only", "-C", action="store_true")

    # Bind commands
    subparsers = ap.add_subparsers()
    for i in Command.__subclasses__():
        sp = subparsers.add_parser(i.name)
        i.setup_args(sp)
        sp.set_defaults(hdlr=i)

    args = ap.parse_args()


    dev = LibOV.OVDevice(mapfile=args.pkg.open('map.txt', 'r'), verbose=args.verbose)

    err = dev.open(bitstream=args.pkg.open('ov3.bit', 'r') if args.load else None)

    if err:
        print("USB: Error opening device\n")
        return 1


    if args.config_only:
        return
    
    dev.dev.write(LibOV.FTDI_INTERFACE_A, b'\x00' * 512, async=False)

    if hasattr(args, 'hdlr'):
        args.hdlr.go(dev, args)

if  __name__ == "__main__":
    main()
