from migen import *
from migen.genlib.cdc import MultiReg
from misoc.interconnect.csr import CSR, AutoCSR

# Button status register of layout:
#    
#   L3 L2 L1 L0 S3 S2 S1 S0
#
#   Lx bits are latched button status bits,
#     cleared-on-write,
#     set on Bx == 1
#
#   Sx bits are the current button status

class _BTN_status_CSR(Module, CSR):
    def __init__(self, btns):
        CSR.__init__(self, size=8)
        self.btn_cur = Signal(4, reset=0)
        self.btn_edge = Signal(4, reset=0)

        self.comb += self.w.eq(Cat(self.btn_cur, self.btn_edge))

        self.sync += If(self.re,
                self.btn_edge.eq(self.btn_cur)).Else(
                self.btn_edge.eq(self.btn_edge | self.btn_cur))

        self.specials += MultiReg(btns, self.btn_cur)


class BTN_status(Module, AutoCSR):
    def __init__(self, btns):
        assert len(btns) <= 4
        self.submodules._stat = _BTN_status_CSR(btns)

