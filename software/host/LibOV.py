import ctypes

libov =  ctypes.cdll.LoadLibrary("./libov.so")

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

class OVDevice:
    def __init__(self):
        self.dev = FTDIDevice()

    def open(self, bitstream=None):
        stat = self.dev.open()
        if stat:
            return stat

        HW_Init(self.dev, bitstream)


    def ioread(self, addr):
        return self.io(addr, 0)

    def iowrite(self, addr, value):
        return self.io(addr | 0x8000, value)

    def io(self, io_ext, value):
        msg = [0x55, (io_ext >> 8), io_ext & 0xFF, value]
        checksum = (sum(msg) & 0xFF)
        msg.append(checksum)
        msg = bytes(msg)

        self.dev.write(FTDI_INTERFACE_A, msg, async=False)
        bb = self.dev.read(FTDI_INTERFACE_A, 5)

        if bb[0] != 0x55:
            raise ProtocolError("No magic found for io response")

        calc_ck = (sum(bb[0:4]) & 0xFF)

        if calc_ck != bb[4]:
            raise ProtocolError("Checksum for response incorrect: expected %02x, got %02x" %
                    (calc_ck, bb[4]))

        return bb[3]





