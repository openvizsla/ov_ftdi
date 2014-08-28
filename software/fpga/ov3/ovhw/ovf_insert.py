from migen.fhdl.std import *
from migen.flow.actor import Source, Sink
from migen.genlib.record import Record

from ovhw.ov_types import ULPI_DATA_D
from ovhw.constants import RXCMD_MAGIC_OVF
from ovhw.perfcounter import CSRStorageEx, Perfcounter

from migen.bank import description

class OverflowInserter(Module, description.AutoCSR):
    def __init__(self):
        self.sink = Sink(ULPI_DATA_D)
        self.source = Source(ULPI_DATA_D)

        self._ctl = CSRStorageEx(1)
        snapshot = self._ctl.re
        reset = self._ctl.storage[0]
        self._num_ovf = Perfcounter(snapshot, reset)
        self._num_total = Perfcounter(snapshot, reset)

        self.comb += If(self.sink.stb, self._num_total.inc())
        self.comb += If(self.source.stb &~ self.source.ack, self._num_ovf.inc())

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

