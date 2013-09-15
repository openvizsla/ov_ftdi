from migen.fhdl.std import *
from migen.bank.description import AutoCSR, CSRStorage, CSRStatus
from migen.flow.actor import Source, Sink
from migen.genlib.fsm import FSM, NextState

from ulpi import ULPI_DATA

# Simple RXCMD / Data streamer
# Uses an absolutely terrible wire-protocol
# Testing-only, need a real module for releaes
#
# Sends packets of the format:
#
#   AC [rxcmd]
#   AD [data]

class RXCStream(Module, AutoCSR):
    def __init__(self):

        self._cfg = CSRStorage(8)
        self._stat = CSRStatus(8)

        self.sink = Sink(ULPI_DATA)
        self.source = Source([("d", 8), ("last", 1)])

        latch_d = Signal()
        latched = Signal(8)
        self.sync += If(latch_d, latched.eq(self.sink.payload.d))

        self.submodules.fsm = FSM()
        self.fsm.act("IDLE",
                self.sink.ack.eq(1),
                If(self.sink.stb & self._cfg.storage[0],
                    latch_d.eq(1),
                    If(self.sink.payload.rxcmd, NextState("RXCMD")
                     ).Else(NextState("UDATA"))))

        self.fsm.act("RXCMD",
                self.source.payload.d.eq(0xAC),
                self.source.stb.eq(1),
                If(self.source.ack,
                    NextState("SENDB"))
                )
        self.fsm.act("UDATA",
                self.source.payload.d.eq(0xAD),
                self.source.stb.eq(1),
                If(self.source.ack,
                    NextState("SENDB"))
                )

        self.fsm.act("SENDB",
                self.source.payload.d.eq(latched),
                self.source.payload.last.eq(1),
                self.source.stb.eq(1),
                If(self.source.ack,
                    NextState("IDLE")))

