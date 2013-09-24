RXCMD_MAGIC_SOP = 0x40
RXCMD_MAGIC_EOP = 0x41     # Packet ended with no error indication
RXCMD_MAGIC_EOP_ERR = 0x42 # Packet terminated by ULPI asserting RXERR
RXCMD_MAGIC_OVF = 0x43     # Packet overflowed in RX path and was clipped

RXCMD_MASK = 0xBF


HF0_ERR =  0x01
HF0_OVF =  0x02
HF0_CLIP = 0x04
HF0_TRUNC = 0x08
