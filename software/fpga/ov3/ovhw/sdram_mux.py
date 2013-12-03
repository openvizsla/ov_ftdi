from migen.genlib.roundrobin import RoundRobin, SP_CE
from migen.fhdl.std import *
from migen.genlib.record import Record

from ovhw.ov_types import sdramHostIf

class SdramMux(Module):
    def __init__(self, sdctl_port):
        self.ports = []
        self.downstream = sdctl_port

    def getPort(self):
        r = Record(sdramHostIf(
            flen(self.downstream.d_read),
            flen(self.downstream.i_addr)))

        self.ports.append(r)
        return r

    def do_finalize(self):
        self.submodules.rr = RoundRobin(len(self.ports), SP_CE)

        busy = Signal()
        adj_last = Signal()


        

        granted = self.rr.grant


        terms = 0

        for i, port in enumerate(self.ports):
            _grant = Signal(name="grant_to_%d" % i)

            self.comb += [
                _grant.eq(granted == i),
                If (_grant,
                    port.connect(self.downstream),
                ),
                self.rr.request[i].eq(port.i_stb),
                ]

        # Busy signal tracks status of downstream controller
        busy_start = Signal()
        busy_stop = Signal()

        self.comb += [
            busy_start.eq(self.downstream.i_stb),
            busy_stop.eq(self.downstream.d_stb & self.downstream.d_term)
            ]

        self.sync += If(busy_start,
            busy.eq(1),
        ).Elif(busy_stop,
            busy.eq(0)
            )

        # Rearbitrate whenever the current command terminates,
        # or when the current master has nothing to offer
        self.comb += self.rr.ce.eq(
            busy_stop | ~(busy | busy_start))


        Module.do_finalize(self)
