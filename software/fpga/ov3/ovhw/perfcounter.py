from migen import *
from misoc.interconnect.csr import CSRStorage, CSRStatus
from ovhw.whacker.util import Acc_inc_sat

class Perfcounter(CSRStatus):
    def __init__(self, snapshot, reset, bits = 32):
        CSRStatus.__init__(self, bits)
        self.submodules.acc = Acc_inc_sat(bits)
        self.sync += If(snapshot, self.status.eq(self.acc.v))
        self.comb += If(reset, self.acc.set(0))

    def inc(self):
        return self.acc.inc()
