import ctypes
import re
import os

_lpath = (os.path.dirname(__file__))
if _lpath == '':
    _lpath = '.'
libov =  ctypes.cdll.LoadLibrary(_lpath + "/libov.so")

class FTDI_Device(ctypes.Structure):
    _fields_ = [
                ('_1', ctypes.c_void_p),
                ('_2', ctypes.c_void_p),
                ]

pFTDI_Device = ctypes.POINTER(FTDI_Device)

# FTDIDevice_Open
FTDIDevice_Open = libov.FTDIDevice_Open
FTDIDevice_Open.argtypes = [pFTDI_Device]
FTDIDevice_Open.restype = ctypes.c_int

# FTDIDevice_Close
FTDIDevice_Close = libov.FTDIDevice_Close
FTDIDevice_Close.argtypes = [pFTDI_Device]

FTDIDevice_Write = libov.FTDIDevice_Write
FTDIDevice_Write.argtypes = [
        pFTDI_Device, # Dev
        ctypes.c_int, # Interface
        ctypes.c_char_p, # Buf
        ctypes.c_size_t, # N
        ctypes.c_bool, # async
        ]
FTDIDevice_Write.restype = ctypes.c_int

p_cb_StreamCallback = ctypes.CFUNCTYPE(
        ctypes.c_int,    # retval
        ctypes.POINTER(ctypes.c_uint8), # buf
        ctypes.c_int, # length
        ctypes.c_void_p, # progress
        ctypes.c_void_p) # userdata

FTDIDevice_ReadStream = libov.FTDIDevice_ReadStream
FTDIDevice_ReadStream.argtypes = [
        pFTDI_Device,    # dev
        ctypes.c_int,    # interface
        p_cb_StreamCallback, # callback
        ctypes.c_void_p, # userdata
        ctypes.c_int, # packetsPerTransfer
        ctypes.c_int, # numTransfers
        ]
FTDIDevice_ReadStream.restype = ctypes.c_int

FTDI_INTERFACE_A = 1
FTDI_INTERFACE_B = 2

# hack
keeper = []

class FTDIDevice:
    def __init__(self):
        self.__is_open = False
        self._dev = FTDI_Device()

    def __del__(self):
        if self.__is_open:
            self.__is_open = False
            FTDIDevice_Close(self._dev)

    def open(self):
        err = FTDIDevice_Open(self._dev)
        if not err:
            self.__is_open = True

        return err

    def write(self, intf, buf, async=False):
        if not isinstance(buf, bytes):
            raise TypeError("buf must be bytes")

        return FTDIDevice_Write(self._dev, intf, buf, len(buf), async)

    def read(self, intf, n):
        buf = []

        def callback(b, prog):
            buf.extend(b)
            return int(len(buf) >= n)

        self.read_async(intf, callback, 4, 4)

        return buf

    def read_async(self, intf, callback, packetsPerTransfer, numTransfers):
        def callback_wrapper(buf, ll, prog, user):
            if ll:
                b = ctypes.string_at(buf, ll)
            else:
                b = b''
            return callback(b, prog)

        cb = p_cb_StreamCallback(callback_wrapper)

        # HACK
        keeper.append(cb)

        return FTDIDevice_ReadStream(self._dev, intf, cb, 
                None, packetsPerTransfer, numTransfers)
        



_HW_Init = libov.HW_Init
_HW_Init.argtypes = [pFTDI_Device, ctypes.c_char_p]

def HW_Init(dev, bitstream):
    return _HW_Init(dev._dev, bitstream)


class ProtocolError(Exception):
    pass

class TimeoutError(Exception):
    pass

class _OV_reg:
    def __init__(self, dev, name, addr):
        self.dev = dev
        self.addr = addr
        self.shadow = 0

    def get(self):
        self.shadow = self.dev.ioread(self.addr)
        return self.shadow

    def set(self, value):
        self.shadow = self.dev.iowrite(self.addr, value)

class _OV_regs:
    def __init__(self, d):
        self._d = d

    def __getattr__(self, attr):
        try:
            return self.__dict__['_d'][attr.upper()]
        except KeyError:
            pass

        raise KeyError("No such register %s - did you specify a mapfile?" % attr)


class OVDevice:
    def __init__(self, mapfile=None, verbose=False):
        self.dev = FTDIDevice()
        self.verbose = verbose

        self.__addrmap = {}

        d = {}
        if mapfile:
            self.__parse_mapfile(mapfile)

            for name, addr in self.__addrmap.items():
                d[name] = _OV_reg(self, name, addr)

        self.regs = _OV_regs(d)




    def __parse_mapfile(self, mapfile):

        for line in open(mapfile).readlines():
            line = line.strip()

            line = re.sub('#.*', '', line)
            if not line:
                continue

            m = re.match('\s*(\w+)\s*=\s*(\w+)\s*', line)
            if not m:
                raise ValueError("Mapfile - could not parse %s" % line)

            name = m.group(1)
            value = int(m.group(2), 16)

            self.__addrmap[name] = value


    def resolve_addr(self, sym):
        if type(sym) == int:
            return sym

        try:
            return int(sym, 16)
        except ValueError:
            pass

        try:
            return self.__addrmap[sym.upper()]
        except KeyError:
            raise ValueError("No map for %s" % sym)

    def open(self, bitstream=None):
        stat = self.dev.open()
        if stat:
            return stat

        HW_Init(self.dev, bitstream)


    def ioread(self, addr):
        return self.io(self.resolve_addr(addr), 0)

    def iowrite(self, addr, value):
        return self.io(self.resolve_addr(addr) | 0x8000, value)

    def io(self, io_ext, value):
        msg = [0x55, (io_ext >> 8), io_ext & 0xFF, value]
        checksum = (sum(msg) & 0xFF)
        msg.append(checksum)

        if self.verbose:
            print("< %s" % " ".join("%02x" % i for i in msg))

        msg = bytes(msg)

        self.dev.write(FTDI_INTERFACE_A, msg, async=False)
        bb = self.dev.read(FTDI_INTERFACE_A, 5)

        if self.verbose:
            print("> %s" % " ".join("%02x" % i for i in bb))

        if bb[0] != 0x55:
            raise ProtocolError("No magic found for io response")

        calc_ck = (sum(bb[0:4]) & 0xFF)

        if calc_ck != bb[4]:
            raise ProtocolError("Checksum for response incorrect: expected %02x, got %02x" %
                    (calc_ck, bb[4]))

        return bb[3]





