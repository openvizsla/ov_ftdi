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

class _mapped_reg:
    def __init__(self, readfn, writefn, name, addr):
        self.readfn = readfn
        self.writefn = writefn
        self.addr = addr
        self.shadow = 0

    def rd(self):
        self.shadow = self.readfn(self.addr)
        return self.shadow

    def wr(self, value):
        self.shadow = self.writefn(self.addr, value)

class _mapped_regs:
    def __init__(self, d):
        self._d = d

    def __getattr__(self, attr):
        try:
            return self.__dict__['_d'][attr.upper()]
        except KeyError:
            pass

        raise KeyError("No such register %s - did you specify a mapfile?" % attr)


UCFG_REG_GO = 0x80
UCFG_REG_ADDRMASK = 0x3F

SMSC_334x_MAGIC = 0x4240009
SMSC_334x_MAP = {
    "VIDL": 0x00,
    "VIDH": 0x01,
    "PIDL": 0x02,
    "PIDH": 0x03,

    "FUNC_CTL": 0x04,
    "FUNC_CTL_SET": 0x05,
    "FUNC_CTL_CLR": 0x06,

    "INTF_CTL": 0x07,
    "INTF_CTL_SET": 0x08,
    "INTF_CTL_CLR": 0x09,

    "OTG_CTL": 0x0A,
    "OTG_CTL_SET": 0x0B,
    "OTG_CTL_CLR": 0x0C,

    "USB_INT_EN_RISE": 0x0D,
    "USB_INT_EN_RISE_SET": 0x0e,
    "USB_INT_EN_RISE_CLR": 0x0f,

    "USB_INT_EN_FALL": 0x10,
    "USB_INT_EN_FALL_SET": 0x11,
    "USB_INT_EN_FALL_CLR": 0x12,

    "USB_INT_STAT": 0x13,
    "USB_INT_LATCH": 0x14,

    "DEBUG": 0x15,

    "SCRATCH": 0x16,
    "SCRATCH_SET": 0x17,
    "SCRATCH_CLR": 0x18,

    "CARKIT": 0x19,
    "CARKIT_SET": 0x1A,
    "CARKIT_CLR": 0x1B,

    "CARKIT_INT_EN": 0x1D,
    "CARKIT_INT_EN_SET": 0x1E,
    "CARKIT_INT_EN_CLR": 0x1F,

    "CARKIT_INT_STAT": 0x20,
    "CARKIT_INT_LATCH": 0x21,

    "HS_COMP_REG":   0x31,
    "USBIF_CHG_DET": 0x32,
    "HS_AUD_MODE":   0x33,

    "VND_RID_CONV": 0x36,
    "VND_RID_CONV_SET": 0x37,
    "VND_RID_CONV_CLR": 0x38,

    "USBIO_PWR_MGMT": 0x39,
    "USBIO_PWR_MGMT_SET": 0x3A,
    "USBIO_PWR_MGMT_CLR": 0x3B,
}


class OVDevice:
    def __init__(self, mapfile=None, verbose=False):
        self.dev = FTDIDevice()
        self.verbose = verbose

        self.__addrmap = {}

        if mapfile:
            self.__parse_mapfile(mapfile)


        self.regs = self.__build_map(self.__addrmap, self.ioread, self.iowrite)
        self.ulpiregs = self.__build_map(SMSC_334x_MAP, self.ulpiread, self.ulpiwrite)


        self.clkup = False
    
    def __build_map(self, addrmap, readfn, writefn):
        d = {}
        for name, addr in addrmap.items():
            d[name] = _mapped_reg(readfn, writefn, name, addr)

        return _mapped_regs(d)


    def __check_clkup(self):
        if self.clkup:
            return True

        self.clkup = self.regs.ucfg_stat.rd() & 0x1

        return self.clkup


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


    def ulpiread(self, addr):
        assert self.__check_clkup()

        self.regs.ucfg_rcmd.wr(UCFG_REG_GO | (addr & UCFG_REG_ADDRMASK))

        while self.regs.ucfg_rcmd.rd() & UCFG_REG_GO:
            pass

        return self.regs.ucfg_rdata.rd()


    def ulpiwrite(self, addr, value):
        assert self.__check_clkup()

        self.regs.ucfg_wdata.wr(value)
        self.regs.ucfg_wcmd.wr(UCFG_REG_GO | (addr & UCFG_REG_ADDRMASK))
        
        while self.regs.ucfg_wcmd.rd() & UCFG_REG_GO:
            pass

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





