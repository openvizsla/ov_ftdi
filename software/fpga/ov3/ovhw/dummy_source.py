from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState
from migen.genlib.fifo import SyncFIFO
from migen.bank import description, csrgen
from migen.flow.actor import Source

class DummySource(Module):
    def __init__(self, base):
        self.source = Source([('d', 8), ('last', 1)])
        
        self.submodules.dummy = FSM()
        
        self.dummy.act("S0",
            self.source.payload.d.eq(base + 0),
            self.source.stb.eq(1),
            If(self.source.ack,
                NextState("S1")
            )
        )

        self.dummy.act("S1",
            self.source.payload.d.eq(base + 1),
            self.source.stb.eq(1),
            If(self.source.ack,
                NextState("S2")
            )
        )

        self.dummy.act("S2",
            self.source.payload.d.eq(base + 2),
            self.source.payload.last.eq(1),
            self.source.stb.eq(1),
            If(self.source.ack,
                NextState("S0")
            )
        )
