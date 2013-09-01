#!/usr/bin/python3

import LibOV
import argparse
import time

def as_ascii(arg):
    if arg == None:
        return None
    return arg.encode('ascii')

class Command:
    @staticmethod
    def setup_args(sp):
        pass

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
        return todeco

    return _i

int16 = lambda x: int(x, 16)

@command('ioread', ('addr', str))
def ioread(dev, addr):
    try:
        addr = "%04x" % addr
    except TypeError:
        pass

    print("%s: %02x" % (addr, dev.ioread(addr)))

@command('iowrite', ('addr', str), ('value', int16))
def iowrite(dev, addr, value):
    dev.iowrite(addr, value)

@command('led-test', ('v', int16))
def ledtest(dev, v):
    dev.regs.leds_out.set(v)

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
    ap.add_argument("--mapfile", "-m")
    ap.add_argument("--bitstream", "-b", type=as_ascii)
    ap.add_argument("--config-only", "-C", action="store_true")

    # Bind commands
    subparsers = ap.add_subparsers()
    for i in Command.__subclasses__():
        sp = subparsers.add_parser(i.name)
        i.setup_args(sp)
        sp.set_defaults(hdlr=i)

    args = ap.parse_args()

    dev = LibOV.OVDevice(mapfile=args.mapfile)

    err = dev.open(bitstream=args.bitstream)

    if err:
        print("USB: Error opening device\n")
        return 1


    if args.config_only:
        return
    
    dev.dev.write(LibOV.FTDI_INTERFACE_A, b'\x00' * 512, async=False)

    args.hdlr.go(dev, args)

if  __name__ == "__main__":
    main()
