from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState
from migen.genlib.record import Record, DIR_M_TO_S
from migen.flow.actor import Source, Sink
from migen.bank.description import AutoCSR, CSRStorage, CSRStatus

ULPI_DATA_D = [("d", 8, DIR_M_TO_S), ("rxcmd", 1, DIR_M_TO_S)]

class RXCmdFilter(Module):
    # Merges/drops unnecessary RXCMDs for packet parsing

    def __init__(self):
        self.sink = Sink(ULPI_DATA_D)
        self.source = Source(ULPI_DATA_D)

        is_sop = Signal()
        is_eop = Signal()
        is_active = Signal()
        is_nactive = Signal()
        is_error = Signal()


        self.comb += [
                is_sop.eq(self.sink.payload.rxcmd & (self.sink.payload.d == 0x40)),
                is_eop.eq(self.sink.payload.rxcmd & (self.sink.payload.d == 0x41)),

                is_active.eq(self.sink.payload.rxcmd & 
                    ~self.sink.payload.d[6] & 
                    (self.sink.payload.d[4:6] == 0x1)),
                is_nactive.eq(self.sink.payload.rxcmd &
                    ~self.sink.payload.d[6] &
                    (self.sink.payload.d[4:6] == 0x0)),
                is_error.eq(self.sink.payload.rxcmd & 
                    ~self.sink.payload.d[6] & 
                    (self.sink.payload.d[4:6] == 0x3)),

                ]

        self.submodules.fsm = FSM()

        def pass_(state):
            return send(state, self.sink.payload.rxcmd, self.sink.payload.d)

        def send(state, is_rxcmd, value):
            return [
                self.source.stb.eq(1),
                self.source.payload.d.eq(value),
                self.source.payload.rxcmd.eq(is_rxcmd),
                If(self.source.ack,
                    self.sink.ack.eq(1),
                    NextState(state)
                )
                ]

        def skip(state):
            return [
                self.sink.ack.eq(1),
                NextState(state)
                ]

        def act(state, *args):
            self.fsm.act(state, 
                If(self.sink.stb,
                    If(~self.sink.payload.rxcmd,
                        pass_(state)
                    ).Else(*args)))


        act("NO_PACKET",
            If(is_sop | is_active,
                send("PACKET", 1, 0x40)
            ).Else(
                skip("NO_PACKET")
            ))

        act("PACKET",
            If(is_eop | is_nactive,
                send("NO_PACKET", 1, 0x41)
            ).Elif(is_error,
                send("NO_PACKET", 1, 0x42)
            ).Else(
                skip("PACKET")
            ))

class TestFilt(Module):
    def __init__(self, clock):

        self.submodules.tr = RXCmdFilter()
        
        self.comb += self.tr.source.ack.eq(self.tr.source.stb)

        self.byte_list = [(1,0x40), (0,0xCA), (1,0x10), (0, 0xFE), (1, 0x41)]

    def do_simulation(self, s):
        if s.cycle_counter > 5 and s.cycle_counter %2 and self.byte_list:
            b = self.byte_list[0]
            print("WR %s" % repr(b))
            self.byte_list = self.byte_list[1:]

            s.wr(self.tr.sink.stb, 1) 
            s.wr(self.tr.sink.payload.d, b[1])
            s.wr(self.tr.sink.payload.rxcmd, b[0])
        else:
            s.wr(self.tr.sink.stb,0)
    

        if s.rd(self.tr.source.stb):
            print("%02x %d" % (s.rd(self.tr.source.payload.d), s.rd(self.tr.source.payload.rxcmd)))


        
if __name__ == "__main__":
    from migen.sim.generic import Simulator, TopLevel

    tl = TopLevel("sdram.vcd")

    test = TestFilt(tl.clock_domains[0])
    sim = Simulator(test, tl)
    sim.run(500)

