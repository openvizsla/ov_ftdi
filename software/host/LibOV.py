import ctypes
import re
import os
import sys
import queue
import threading
import collections
from usb_interp import USBInterpreter

_lpath = (os.path.dirname(__file__))
if _lpath == '':
    _lpath = '.'

if sys.platform == 'darwin':
    _lib_suffix = 'dylib'
elif sys.platform == 'win32':
	_lib_suffix = 'dll'
else:
    _lib_suffix = 'so'

libov = ctypes.cdll.LoadLibrary(_lpath + "/libov." + _lib_suffix)

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

# void ChandlePacket(unsigned int ts, unsigned int flags, unsigned char *buf, unsigned int len)
ChandlePacket = libov.ChandlePacket
ChandlePacket.argtypes = [
    ctypes.c_ulonglong, # ts
    ctypes.c_int, # flags
    ctypes.c_char_p, # buf
    ctypes.c_int, # len
]

# int FTDIEEP_Erase(FTDIDevice *dev)
FTDIEEP_Erase = libov.FTDIEEP_Erase
FTDIEEP_Erase.argtypes = [
        pFTDI_Device,    # dev
        ]
FTDIEEP_Erase.restype = ctypes.c_int

# int FTDIEEP_CheckAndProgram(FTDIDevice *dev, unsigned int number)
FTDIEEP_CheckAndProgram = libov.FTDIEEP_CheckAndProgram
FTDIEEP_CheckAndProgram.argtypes = [
        pFTDI_Device,    # dev
        ctypes.c_int,    # serial number
        ]
FTDIEEP_CheckAndProgram.restype = ctypes.c_int

# int FTDIEEP_SanityCheck(FTDIDevice *dev, bool verbose)
FTDIEEP_SanityCheck = libov.FTDIEEP_SanityCheck
FTDIEEP_SanityCheck.argtypes = [
        pFTDI_Device,    # dev
        ctypes.c_bool,   # verbose
        ]
FTDIEEP_SanityCheck.restype = ctypes.c_int


FTDI_INTERFACE_A = 1
FTDI_INTERFACE_B = 2

# hack
keeper = []

class FTDIDevice:
    def __init__(self):
        self.__is_open = False
        self._dev = FTDI_Device()

    def __del__(self):
        self.close()

    def open(self):
        err = FTDIDevice_Open(self._dev)
        if not err:
            self.__is_open = True

        return err

    def close(self):
        if self.__is_open:
            self.__is_open = False
            FTDIDevice_Close(self._dev)

    def write(self, intf, buf, async_=False):
        if not isinstance(buf, bytes):
            raise TypeError("buf must be bytes")

        return FTDIDevice_Write(self._dev, intf, buf, len(buf), async_)

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
        # uncomment next lines to use C code to parse packets
        #return FTDIDevice_ReadStream(self._dev, intf, p_cb_StreamCallback(libov.CStreamCallback), 
        #        cb, packetsPerTransfer, numTransfers)

    def eeprom_erase(self):
        return FTDIEEP_Erase(self._dev)

    def eeprom_program(self, serialno):
        return FTDIEEP_CheckAndProgram(self._dev, serialno)

    def eeprom_sanitycheck(self, verbose=False):
        return FTDIEEP_SanityCheck(self._dev, verbose)

_FPGA_GetConfigStatus = libov.FPGA_GetConfigStatus
_FPGA_GetConfigStatus.restype = ctypes.c_int
_FPGA_GetConfigStatus.argtypes = [pFTDI_Device]

def FPGA_GetConfigStatus(dev):
    return _FPGA_GetConfigStatus(dev._dev)

_HW_Init = libov.HW_Init
_HW_Init.argtypes = [pFTDI_Device, ctypes.c_char_p]

def HW_Init(dev, bitstream):
    return _HW_Init(dev._dev, bitstream)


class ProtocolError(Exception):
    pass

class TimeoutError(Exception):
    pass

class _mapped_reg:
    def __init__(self, readfn, writefn, name, addr, size):
        self.readfn = readfn
        self.writefn = writefn
        self.addr = addr
        self.size = size
        self.shadow = 0

    def rd(self):
        self.shadow = 0
        for i in range(self.size):
            self.shadow <<= 8
            self.shadow |= self.readfn(self.addr + i)
        return self.shadow

    def wr(self, value):
        self.shadow = value
        for i in range(self.size):
            self.writefn(self.addr + self.size - 1 - i, (value >> (i * 8)) & 0xFF)

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


INCOMPLETE = -1
UNMATCHED = 0
class baseService:
    def matchMagic(self, byt):
        return byt == self.MAGIC

    def getNeededSizeForMagic(self, byt):
        return self.NEEDED_FOR_SIZE

    def presentBytes(self, b):
        if not self.matchMagic(b[0]):
            return UNMATCHED

        if len(b) < self.getNeededSizeForMagic(b[0]):
            return INCOMPLETE

        size = self.getPacketSize(b)

        if len(b) < size:
            return INCOMPLETE

        self.consume(b[:size])

        return size

class IO:
    class __IOService(baseService):
        MAGIC = 0x55
        NEEDED_FOR_SIZE = 1

        def __init__(self):
            self.q = queue.Queue()

        def getPacketSize(self, buf):
            return 5

        def consume(self, buf):
            assert buf[0] == self.MAGIC
            assert len(buf) == 5

            calc_ck = (sum(buf[0:4]) & 0xFF)

            if calc_ck != buf[4]:
                raise ProtocolError(
                    "Checksum for response incorrect: expected %02x, got %02x" %
                    (calc_ck, buf[4])
                )

            self.q.put((buf[1] << 8 | buf[2], buf[3]))

    def __init__(self):
        self.service = IO.__IOService()

    def do_read(self, addr, timeout=None):
        return self.__txn(addr, 0, timeout)

    def do_write(self, addr, value, timeout=None):
        return self.__txn(0x8000 | addr, value, timeout)

    def __txn(self, io_ext, value, timeout):
        msg = [0x55, (io_ext >> 8), io_ext & 0xFF, value]
        checksum = (sum(msg) & 0xFF)
        msg.append(checksum)
        msg = bytes(msg)

        self.service.write(msg)

        try:
            resp = self.service.q.get(True, timeout)
        except queue.Empty:
            raise TimeoutError("IO access timed out")

        r_addr, r_value = resp

        assert r_addr == io_ext

        return r_value

# Basic Test service for testing stream rates and ordering
# Ideally we'd verify the entire LFSR, but python is too slow
# As it is, the rates are CPU-bound
class LFSRTest:
    __stats = collections.namedtuple('LFSR_Stat', 
            ['total', 'error'])

    class __LFSRTestService(baseService):
        MAGIC = 0xAA

        NEEDED_FOR_SIZE = 2

        def __init__(self):
            self.total = 0
            self.reset()

        def reset(self):
            self.state = None
            self.error = 0
            self.total = 0

        def getPacketSize(self, buf):
            # overhead is magic, length
            return buf[1] + 2

        def consume(self, buf):
            assert buf[0] == self.MAGIC
            assert buf[1] + 2 == len(buf)

            self.total += buf[1]

            if self.state != None:
                if buf[2] & 0xFE != (self.state << 1) & 0xFE:
                    self.error = 1

            self.state = buf[-1]

    def __init__(self):
        self.service = LFSRTest.__LFSRTestService()

        self.reset = self.service.reset

    def stats(self):
        return LFSRTest.__stats(total=self.service.total, error=self.service.error)

def hd(x):
    return " ".join("%02x" % i for i in x)

MAX_PACKET_SIZE = 800

#  Physical layer error
HF0_ERR =  0x01
# RX Path Overflow
HF0_OVF =  0x02
# Clipped by Filter
HF0_CLIP = 0x04
# Clipped due to packet length (> MAX_PACKET_SIZE bytes)
HF0_TRUNC = 0x08
# First packet of capture session; IE, when the cap hardware was enabled
HF0_FIRST = 0x10
# Last packet of capture session; IE, when the cap hardware was disabled
HF0_LAST = 0x20

def decode_flags(flags):
    ret = ""
    ret += "Error " if flags & HF0_ERR else ""
    ret += "Overflow" if flags & HF0_OVF else ""
    ret += "Clipped " if flags & HF0_CLIP else ""
    ret += "Truncated " if flags & HF0_TRUNC else ""
    ret += "First " if flags & HF0_FIRST else ""
    ret += "Last " if flags & HF0_LAST else ""
    return ret.rstrip()

class RXCSniff:
    class __RXCSniffService(baseService):
        import crcmod
        data_crc = staticmethod(crcmod.mkCrcFun(0x18005))

        def getNeededSizeForMagic(self, b):
            if b == 0xA0:
                return 5
            return 1

        def __init__(self):
            self.last_rxcmd = 0

            self.usbbuf = []

            self.highspeed = False

            self.ui = USBInterpreter(self.highspeed)

            self.handlers = [self.handle_usb_verbose]

            self.got_start = False


        def matchMagic(self, byt):
            return byt == 0xAC or byt == 0xAD or byt == 0xA0

        def getPacketSize(self, buf):
            if buf[0] != 0xA0:
                return 2
            else:
                #print("SIZING: %s" % " ".join("%02x" %i for i in buf))
                flags = buf[1] | buf[2] << 8
                if flags & HF0_TRUNC:
                    return MAX_PACKET_SIZE + 8
                return (buf[4] << 8 | buf[3]) + 8


        def consume(self, buf):
            if buf[0] == 0xA0:
                flags = buf[1] | buf[2] << 8
                orig_len = buf[4] << 8 | buf[3]
                ts = buf[5] | buf[6] << 8 | buf[7] << 16

                if flags != 0 and flags != HF0_FIRST and flags != HF0_LAST:
                    print("PERR: %04X (%s)" % (flags, decode_flags(flags)))
               
                if flags & HF0_FIRST:
                    self.got_start = True

                if self.got_start:
                    self.handle_usb(ts, buf[8:], flags, orig_len)

                if flags & HF0_LAST:
                    self.got_start = False

        def handle_usb(self, ts, buf, flags, orig_len):
            for handler in self.handlers:
                handler(ts, buf, flags, orig_len)

        def handle_usb_verbose(self, ts, buf, flags, orig_len):
#                ChandlePacket(ts, flags, buf, len(buf))
                self.ui.handlePacket(ts, buf, flags, orig_len)

            
    def __init__(self):
        self.service = RXCSniff.__RXCSniffService()


class SDRAMRead:
    class __SDRAMReadService(baseService):
        def getNeededSizeForMagic(self, b):
            return 2

        def __init__(self, verbose, services):
            self.__buf = b""
            self.__services = services
            self.__verbose = verbose

        def matchMagic(self, byt):
            return byt == 0xD0

        def getPacketSize(self, buf):
            return (buf[1] + 1) * 2 + 2

        def consume(self, b):
            #print("SDRAM", ''.join("%02x"% r for r in b))
            b = b[2:]
            if self.__verbose and b:
                print("SD> %s" % " ".join("%02x" % i for i in b))

            self.__buf += b

            incomplete = False

            while self.__buf and not incomplete:
                for service in self.__services:
                    code = service.presentBytes(self.__buf)
                    if code == INCOMPLETE:
                        incomplete = True
                        break
                    elif code:
                        self.__buf = self.__buf[code:]
                        break
                else:
                    print("Unmatched byte %02x - discarding" % self.__buf[0])
                    self.__buf = self.__buf[1:]
            pass
        
    def __init__(self, verbose, services):
        self.service = SDRAMRead.__SDRAMReadService(verbose, services)

class Dummy:
    class __DummyService(baseService):
        def getNeededSizeForMagic(self, b):
            return 1
        def __init__(self):
            pass
        def matchMagic(self, byt):
            return byt == 0xE0 or byt == 0xe8
        def getPacketSize(self, buf):
            return 3
        def consume(self, buf):
            assert ''.join("%02x"% r for r in buf) in ["e0e1e2", "e8e9ea"], buf
        
    def __init__(self):
        self.service = Dummy.__DummyService()

class OVDevice:
    def __init__(self, mapfile=None, verbose=False):
        self.__is_open = False

        self.dev = FTDIDevice()
        self.verbose = verbose

        self.__addrmap = {}

        if mapfile:
            self.__parse_mapfile(mapfile)


        self.regs = self.__build_map(self.__addrmap, self.ioread, self.iowrite)
        self.ulpiregs = self.__build_map({x: (y, 1) for x, y in SMSC_334x_MAP.items()}, self.ulpiread, self.ulpiwrite)


        self.clkup = False


        self.io = IO()

        self.lfsrtest = LFSRTest()
        self.rxcsniff = RXCSniff()
        self.sdram_read = SDRAMRead(False, [self.rxcsniff.service])
        self.dummy = Dummy()

        self.__services = [self.io.service, self.lfsrtest.service, self.rxcsniff.service, self.sdram_read.service, self.dummy.service]

        # Inject a write function to the services
        for service in self.__services:
            def write(msg):
                if self.verbose:
                    print("< %s" % " ".join("%02x" % i for i in msg))

                self.dev.write(FTDI_INTERFACE_A, msg, async_=False)

            service.write = write
    
    def __comms(self):
        self.__buf = b""

        def callback(b, prog):
            try:
                if self.verbose and b:
                    print("> %s" % " ".join("%02x" % i for i in b))

                self.__buf += b

                incomplete = False

                while self.__buf and not incomplete:
                    for service in self.__services:
                        code = service.presentBytes(self.__buf)
                        if code == INCOMPLETE:
                            incomplete = True
                            break
                        elif code:
                            self.__buf = self.__buf[code:]
                            break
                    else:
                        print("Unmatched byte %02x - discarding" % self.__buf[0])
                        self.__buf = self.__buf[1:]

                return int(self.__comm_term) 
            except Exception as e:
                self.__comm_term = True
                self.__comm_exc = e
                return 1

        while not self.__comm_term:
            self.dev.read_async(FTDI_INTERFACE_A, callback, 8, 16)

        if self.__comm_exc:
            raise self.__comm_exc
            
    def __build_map(self, addrmap, readfn, writefn):
        d = {}
        for name, (addr, size) in addrmap.items():
            d[name] = _mapped_reg(readfn, writefn, name, addr, size)

        return _mapped_regs(d)


    def __check_clkup(self):
        if self.clkup:
            return True

        self.clkup = self.regs.ucfg_stat.rd() & 0x1

        return self.clkup


    def __parse_mapfile(self, mapfile):

        for line in mapfile.readlines():
            line = line.strip().decode('utf-8')

            line = re.sub('#.*', '', line)
            if not line:
                continue

            m = re.match('\s*(\w+)\s*=\s*(\w+)(:\w+)?\s*', line)
            if not m:
                raise ValueError("Mapfile - could not parse %s" % line)

            name = m.group(1)
            value = int(m.group(2), 16)
            if m.group(3) is None:
                size = 1
            else:
                size = int(m.group(3)[1:], 16) + 1 - value
                assert size > 1

            self.__addrmap[name] = value, size


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

    def __del__(self):
        if self.__is_open:
            self.close()

    def isLoaded(self):
        assert self.__is_open
        return self.loaded

    def open(self, bitstream=None):
        if self.__is_open:
            raise ValueError("OVDevice doubly opened")

        stat = self.dev.open()
        if stat:
            return stat

        if not isinstance(bitstream, bytes) and hasattr(bitstream, 'read'):

            # FIXME: Current bit_file code is heavily dependent on fstream ops
            #  and isn't nice to call with a python file-like object
            #
            # Workaround this by emitting a tempfile
            import tempfile
            import os

            bitfile = tempfile.NamedTemporaryFile(delete=False)

            try:
                bitfile.write(bitstream.read())
                bitfile.close()

                HW_Init(self.dev, bitfile.name.encode('ascii'))
                self.loaded = True
           
            finally:
                # Make sure we cleanup the tempfile
                os.unlink(bitfile.name)

        elif isinstance(bitstream, bytes) or bitstream == None:
            pre_load = FPGA_GetConfigStatus(self.dev) == 0

            HW_Init(self.dev, bitstream)
            
            if bitstream:
                self.loaded = True
            else:
                self.loaded = pre_load

        else:
            raise TypeError("bitstream must be bytes or file-like")
        
    
        self.commthread = threading.Thread(target=self.__comms, daemon=True)
        self.__comm_term = False
        self.__comm_exc = None

        self.commthread.start()

        self.__comm_term = False
        self.__is_open = True

    def close(self):
        if not self.__is_open:
            raise ValueError("OVDevice doubly closed")

        self.__comm_term = True
        self.commthread.join()

        self.dev.close()

        self.__is_open = False


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
        return self.io.do_read(self.resolve_addr(addr))

    def iowrite(self, addr, value):
        return self.io.do_write(self.resolve_addr(addr), value)






