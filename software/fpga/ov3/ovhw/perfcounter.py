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

# CSRStorage with accessible re
class CSRStorageEx(CSRStorage):
    def __init__(self, *args, **kwargs):
        CSRStorage.__init__(self, *args, **kwargs)
        self.re = Signal()
    
    def do_finalize(self, busword):
        CSRStorage.do_finalize(self, busword)
        self.comb += self.re.eq(self.simple_csrs[0].re)
