from migen.fhdl.std import *
from migen.bank.description import CSR, AutoCSR

class _bist_cmd_reg(Module, CSR):
    B_GO = 7

    def __init__(self, trig, busy, cmd, ok):
        CSR.__init__(self, size=8)
        self.trig = trig
        self.trig.reset = 0
        self.busy = busy
        self.cmd = cmd
        self.ok = ok

        self.sync += [
                If(self.re & self.r[self.B_GO],
                    self.trig.eq(1)
                ).Elif(~self.busy,
                    self.trig.eq(0)
                ),

                If(self.re,
                    self.cmd.eq(self.r[0:4])
                )]

        _o = Signal(8)
        self.comb += [
            self.w.eq(_o),
            _o[7].eq(self.trig),
            _o[6].eq(self.busy),
            _o[5].eq(self.ok),
            _o[:4].eq(self.cmd),
            ]

class SDRAMBISTCfg(Module, AutoCSR):
    def __init__(self, bist):
        self.submodules.cmd = _bist_cmd_reg(bist.start, bist.busy, bist.sel_test, bist.ok)


