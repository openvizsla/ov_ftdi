import migen

from migen.genlib.record import DIR_M_TO_S, DIR_S_TO_M

ULPI_DATA_D = [("d", 8, DIR_M_TO_S), ("rxcmd", 1, DIR_M_TO_S)]

ULPI_DATA_TAG = [
    ("ts", 64, DIR_M_TO_S),
    ("d", 8, DIR_M_TO_S),
    ("is_start", 1, DIR_M_TO_S),
    ("is_end", 1, DIR_M_TO_S),
    ("is_err", 1, DIR_M_TO_S),
    ("is_ovf", 1, DIR_M_TO_S),
]

# Streaming SDRAM host interface
def sdramHostIf(dw, aw):
    return [
        ("i_wr", 1, DIR_M_TO_S),      # Write/Read
        ("i_addr", aw, DIR_M_TO_S),   # Address
        ("i_stb", 1, DIR_M_TO_S),     # Issue request
        ("i_ack", 1, DIR_S_TO_M),     # Issue acknowledge

        # Data "strobe". For read cycles, indicates data is present and fresh this cycle
        # For write cycles, indicates that data present on d_write was latched and new
        # data should be asserted
        ("d_stb", 1, DIR_S_TO_M),     

        # Indicates that the master wishes to terminate the stream.
        # d_stb will not reassert. For reads, the host may keep the data
        # For writes, the data is not written
        ("d_term", 1, DIR_M_TO_S),

        # Data write/read ports
        ("d_write", dw, DIR_M_TO_S),
        ("d_read", dw, DIR_S_TO_M)

        ]
