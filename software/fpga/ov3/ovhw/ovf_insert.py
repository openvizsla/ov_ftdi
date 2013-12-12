from migen.fhdl.std import *
from migen.flow.actor import Source, Sink
from migen.genlib.record import Record

from ovhw.ov_types import ULPI_DATA_D
from ovhw.constants import RXCMD_MAGIC_OVF

class OverflowInserter(Module):
    def __init__(self):
        self.sink = Sink(ULPI_DATA_D)
        self.source = Source(ULPI_DATA_D)

        valid = Signal()
        data = Record(ULPI_DATA_D)


        self.comb += [
            If(self.sink.stb,
                self.sink.ack.eq(1),
            )]

        self.sync += [
            If(self.sink.stb,
                valid.eq(1),
                If(valid & ~self.source.ack,
                    data.rxcmd.eq(1),
                    data.d.eq(RXCMD_MAGIC_OVF),
                ).Else(
                    data.eq(self.sink.payload)
                )
            ).Elif(self.source.ack,
                valid.eq(0)
            )]

        self.comb += [
            self.source.stb.eq(valid),
            self.source.payload.eq(data)
            ]

