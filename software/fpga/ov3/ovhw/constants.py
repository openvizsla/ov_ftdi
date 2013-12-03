RXCMD_MAGIC_SOP = 0x40
RXCMD_MAGIC_EOP = 0x41     # Packet ended with no error indication
RXCMD_MAGIC_OVF = 0x43     # Packet overflowed in RX path and was clipped
RXCMD_MAGIC_NOP = 0x44

RXCMD_MASK = 0xBF


#  Physical layer error
HF0_ERR =  0x01

# RX Path Overflow
HF0_OVF =  0x02

# Clipped by Filter
HF0_CLIP = 0x04

# Clipped due to packet length (> 800 bytes)
HF0_TRUNC = 0x08

# First packet of capture session; IE, when the cap hardware was enabled
HF0_FIRST = 0x10

# Last packet of capture session; IE, when the cap hardware was disabled
HF0_LAST = 0x20

