from migen import *
from misoc.interconnect.stream import Endpoint
from migen.fhdl.bitcontainer import bits_for
from migen.genlib.fsm import FSM, NextState

from ovhw.whacker.util import dmatpl
from ovhw.constants import *

from ovhw.ov_types import D_LAST, ULPI_DATA_D

def _inc(signal, modulo, dest_signal=None):
    if type(dest_signal) == type(None):
        dest_signal = signal

    assert modulo == 2**len(signal)
    assert len(dest_signal) == len(signal)
    return dest_signal.eq(signal + 1)

class Consumer(Module):
    def __init__(self, port, depth):
        self.sink = Endpoint(dmatpl(depth))
        self.source = Endpoint(D_LAST)
        self.busy = Signal()

        self.pos = Signal(max=depth, reset=0)
        self.pos_next = Signal(max=depth, reset=0)
        self.ct = Signal(max=depth, reset=0)
        self.ct_next = Signal(max=depth)


        self.comb += [
                self.ct_next.eq(self.ct),

                self.pos_next.eq(self.pos),
                port.adr.eq(self.pos_next),
                ]

        self.sync += [
            self.pos.eq(self.pos_next),
            self.ct.eq(self.ct_next)
            ]

        self.submodules.fsm = FSM()

        self.fsm.act("IDLE",
                self.busy.eq(0),
                If(self.sink.stb,
                    self.busy.eq(1),
                    self.sink.ack.eq(1),
                    self.pos_next.eq(self.sink.payload.start),
                    self.ct_next.eq(self.sink.payload.count-1),
                    NextState('d'),
                )
                )
        
        self.fsm.act("d",
                self.busy.eq(1),
                self.source.stb.eq(1),
                self.source.payload.d.eq(port.dat_r),

                If(self.ct == 0,
                    self.source.payload.last.eq(1)),

                If(self.source.ack,
                    If(self.ct,
                        _inc(self.pos, depth, self.pos_next),
                        self.ct_next.eq(self.ct - 1),
                    ).Else(
                        NextState("IDLE")
                    )
                )
            )

