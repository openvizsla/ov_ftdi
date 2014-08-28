from migen.fhdl.std import *
from migen.bank import description
from ovhw.whacker.util import Acc_inc_sat

class Perfcounter(description.CSRStatus):
    def __init__(self, snapshot, reset, bits = 32):
        description.CSRStatus.__init__(self, bits)
        self.submodules.acc = Acc_inc_sat(bits)
        self.sync += If(snapshot, self.status.eq(self.acc.v))
        self.comb += If(reset, self.acc.set(0))

    def inc(self):
        return self.acc.inc()

# CSRStorage with accessible re
class CSRStorageEx(description.CSRStorage):
    def __init__(self, *args, **kwargs):
        description.CSRStorage.__init__(self, *args, **kwargs)
        self.re = Signal()
    
    def do_finalize(self, busword):
        description.CSRStorage.do_finalize(self, busword)
        self.comb += self.re.eq(self.simple_csrs[0].re)
