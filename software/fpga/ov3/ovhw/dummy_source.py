from migen import *
from migen.genlib.fsm import FSM, NextState
from misoc.interconnect.stream import Endpoint

class DummySource(Module):
    def __init__(self, base, data = 300, idle = 1000):
        self.source = Endpoint([('d', 8), ('last', 1)])
        
        self.submodules.dummy = FSM()
        
        dummy_count = Signal(max=max(idle, data))
        dummy_count_next = Signal(max=max(idle, data))
        self.sync += dummy_count.eq(dummy_count_next)
        self.comb += dummy_count_next.eq(dummy_count)

        self.dummy.act("S0",
            self.source.payload.d.eq(base + 0),
            self.source.stb.eq(1),
            dummy_count_next.eq(0),
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
            self.source.payload.d.eq(dummy_count[0:8]),
            self.source.stb.eq(1),
            If(self.source.ack,
                If(dummy_count != data,
                    dummy_count_next.eq(dummy_count+1)
                ).Else(dummy_count_next.eq(0),
                    self.source.payload.last.eq(1),
                    NextState("S3")
                )
            )
        )

        self.dummy.act("S3",
                If(dummy_count != idle,
                    dummy_count_next.eq(dummy_count+1)
                ).Else(dummy_count_next.eq(0),
                    NextState("S0")
                )
            )
