import migen

from migen.genlib.record import DIR_M_TO_S, DIR_S_TO_M

D_LAST = [("d", 8), ("last", 1)]

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

"""

An example transfer: 

- Write AD50, AD51, ..., ADB3 to address 000050, 000051, ..., 0000B3
- Read back from 000055, ..., 000058

The d_stb de-assertions are arbitrary.

(paste into: http://wavedrom.github.io/editor.html)

{signal: [
['issue',
['M2S',
  {name: 'i_wr',     wave: 'x1...x..........|.....|0...x........', node:'.......................'},
  {name: 'i_addr',   wave: 'x4...x..........|.....|4...x........', node:'.......................', data: ["24'h000050", "24'h000055"]},
  {name: 'i_stb',    wave: '01...0..........|.....|1...0........', node:'.c.....................'},
],
['S2M',
  {name: 'i_ack',    wave: '0...10..........|.....|...10........', node:'....a..................'},
],
],
  {},
['data',
['M2S',
  {name: 'd_write',  wave: 'x3........33.333|33x..|.............', node:'..........d............', data: ["16'hAD50", "AD51", "AD52", "AD53", "AD54", "", "ADB2", "ADB3"]},
  {name: 'd_term',   wave: '0...............|..10.|..........1.0', node:'...................e...'},
],
['S2M',
  {name: 'd_stb',    wave: '0........1.01...|...0.|......1.01010', node:'.........b..........f..'},
  {name: 'd_read',   wave: 'x...............|.....|......55.5.5x', node:'.......................', data: ["AD55", "AD56", "AD57", "AD58"]},
],
],
  {},
  {name: 'clk',      wave: 'p...............|.....|.............', node:'.......................'}, 
],
  edge: ['a~->b', 'c~->a', 'b~>d', 'e~>f'],
}

"""
