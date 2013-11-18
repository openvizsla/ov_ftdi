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

