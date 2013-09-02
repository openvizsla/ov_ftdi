from migen.fhdl.std import *
from migen.genlib.record import Record
from migen.flow.actor import Source, Sink
from csr_master import CMD_REC

from migen.genlib.fsm import FSM, NextState
from migen.genlib.roundrobin import RoundRobin, SP_CE


# Simple statemachine to turn incoming datastream
# into CSR bus accesses

# transactions into 
class BusDecode(Module):
    def __init__(self):
        self.busy=Signal()
        self.sink = Sink([('d',8)])
        self.source = Source(CMD_REC)

        sm = FSM(reset_state="IDLE")
        self.submodules += sm

        # Basic checksum

        token = self.source.payload
        token_next = Record(CMD_REC)

        self.sync += token.eq(token_next)
        self.comb += token_next.eq(token)



        sm.act("IDLE",
                self.sink.ack.eq(1),
                If(self.sink.stb,
                    If(self.sink.payload.d == 0x55,
                        NextState("ADRH")
                    )))

        def parse_state(st, to, *update):
            sm.act(st, 
                self.sink.ack.eq(1),
                If(self.sink.stb,
                    NextState(to),
                    *update
                    ))

        parse_state('ADRH', 'ADRL', 
                token_next.wr.eq(self.sink.payload.d[7]), 
                token_next.a[8:14].eq(self.sink.payload.d[:6]))

        parse_state('ADRL', 'DATA',  token_next.a[0:8].eq(self.sink.payload.d)),
        parse_state('DATA', 'CKSUM', token_next.d.eq(self.sink.payload.d)),

        sm.act("CKSUM",
                self.sink.ack.eq(1),
                If(self.sink.stb,
                        NextState('ISSUE')
                )    
        )

        sm.act("ISSUE",
                self.source.stb.eq(1),
                If(self.source.ack,
                    NextState('IDLE')))
                    

class BusEncode(Module):
    def __init__(self):

        self.busy = Signal()
        self.sink = Sink(CMD_REC)
        self.source = Source([('d',8), ('last',1)])

        sm = FSM(reset_state="IDLE")
        self.submodules += sm

        self.comb += [
            self.source.stb.eq(0),
            self.source.payload.last.eq(0)
            ]


        ssum = Signal(8)

        token_next = Record(CMD_REC)
        token = Record(CMD_REC)
        self.comb += token_next.eq(token)
        self.sync += token.eq(token_next)

        sm.act("IDLE",
                If(self.sink.stb,
                    self.sink.ack.eq(1),
                    token_next.eq(self.sink.payload),
                    NextState('c0')))

        _outs = [
            0x55,
            Cat(token.a[8:14], 0, token.wr),
            token.a[0:8],
            token.d,
            ssum
            ]

        s = _outs[0]
        for i in _outs[1:-1]:
            s = s + i
        self.sync += ssum.eq(s)


        for c, v in enumerate(_outs):
            _last = 1 if c == len(_outs) - 1 else 0
            _next = "IDLE" if _last else "c%d" % (c + 1)
            sm.act("c%d" % c,
                    self.source.stb.eq(1),
                    self.source.payload.d.eq(v),
                    self.source.payload.last.eq(_last),
                    If(self.source.ack,
                        NextState(_next)
                        ))


class BusInterleave(Module):
    def __init__(self, mux_ports):
        self.source = Source([('d', 8)])

        n = len(mux_ports)

        self.submodules.rr = RoundRobin(n, SP_CE)

        granted = self.rr.grant

        release = Signal()
        request = Signal()

        released = Signal(reset=1)

        self.sync += If(request, released.eq(0)).Elif(
                        release, released.eq(1))

        self.comb += request.eq(self.rr.request != 0)


        self.comb += self.rr.ce.eq(request & released)

        for i, port in enumerate(mux_ports):
            self.comb += [
                If(granted == i,
                    self.source.stb.eq(port.source.stb),
                    self.source.payload.d.eq(port.source.payload.d),
                    port.source.ack.eq(self.source.ack),

                    If(port.source.payload.last,
                        release.eq(1))),

                self.rr.request[i].eq(port.source.stb)
                ]



                    


                    
if __name__ == "__main__":
    from migen.fhdl import verilog
    
    m = Module()
    m.submodules.dec = BusDecode()
    #m.submodules.enc = BusEncode()

    print(verilog.convert(m))
