from migen.fhdl.std import *
from migen.flow.actor import Source, Sink
from migen.fhdl.bitcontainer import bits_for
from migen.genlib.fsm import FSM, NextState

from ovhw.whacker.util import dmatpl
from ovhw.ulpi import ULPI_DATA
from ovhw.constants import *

D_LAST = [("d", 8), ("last", 1)]


def _inc(signal, modulo, dest_signal=None):
    if type(dest_signal) == type(None):
        dest_signal = signal

    assert modulo == 2**flen(signal)
    assert flen(dest_signal) == flen(signal)
    return dest_signal.eq(signal + 1)

class Consumer(Module):
    def __init__(self, port, depth):
        self.sink = Sink(dmatpl(depth))
        self.source = Source(D_LAST)
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



class TestConsumer(Module):
    def __init__(self):
        from migen.actorlib.sim import SimActor, Dumper, Token

        class PORT(Module):
            def __init__(self, aw, dw):
                self.adr = Signal(aw)
                self.dat_r = Signal(dw)

                self.sync += self.dat_r.eq(self.adr)

        self.submodules.port = PORT(bits_for(1024), 8)

        def gen():
            yield  Token('source', {"start": 0, "count" : 4})
            yield None
            yield  Token('source', {"start": 555, "count" : 77})
            

        class SimSource(SimActor):
            def __init__(self):
                self.source = Source(dmatpl(1024))
                SimActor.__init__(self, gen())

        self.submodules.src = SimSource()
        self.submodules.c = Consumer(self.port, 1024)
        self.comb += self.c.sink.connect(self.src.source)
        self.comb += self.src.busy.eq(0)

        self.submodules.dmp = Dumper(D_LAST)
        self.comb += self.c.source.connect(self.dmp.result)
        self.comb += self.dmp.busy.eq(0)



if __name__ == '__main__':
    from migen.sim.generic import Simulator, TopLevel
    tl = TopLevel("testcons.vcd")
    test = TestConsumer()
    sim = Simulator(test, tl)
    sim.run(200)
    

