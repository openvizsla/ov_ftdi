from migen import *
from misoc.interconnect.csr import AutoCSR, CSRStatus, CSRStorage
from misoc.interconnect.stream import Endpoint
from migen.genlib.fsm import FSM, NextState

from ovhw.whacker.consumer import Consumer
from ovhw.whacker.producer import Producer

from ovhw.constants import *

from ovhw.ov_types import D_LAST, ULPI_DATA_D

class Whacker(Module, AutoCSR):
    def __init__(self, depth):
        self._cfg = CSRStorage(1)

        debug_signals = 1

        storage = Memory(8, depth)
        self.specials += storage

        wrport = storage.get_port(write_capable=True)
        self.specials += wrport
        rdport = storage.get_port(async_read=False)
        self.specials += rdport

        self.submodules.consumer = Consumer(rdport, depth)
        self.submodules.producer = Producer(wrport, depth, self.consumer.pos, self._cfg.storage[0])
        

        self.sink = self.producer.ulpi_sink
        self.comb += self.producer.out_addr.connect(self.consumer.sink)
        self.source = self.consumer.source

        # Debug signals for state tracing
        if debug_signals:
            self._cons_lo = CSRStatus(8)
            self._cons_hi = CSRStatus(8)
            self._prod_lo = CSRStatus(8)
            self._prod_hi = CSRStatus(8)
            self._prod_hd_lo = CSRStatus(8)
            self._prod_hd_hi = CSRStatus(8)
            self._size_lo = CSRStatus(8)
            self._size_hi = CSRStatus(8)

            self._prod_state = CSRStatus(8)
            self._cons_status = CSRStatus(8)

            self._last_start_lo = CSRStatus(8)
            self._last_start_hi = CSRStatus(8)
            self._last_count_lo = CSRStatus(8)
            self._last_count_hi = CSRStatus(8)
            self._last_pw_lo = CSRStatus(8)
            self._last_pw_hi = CSRStatus(8)

            self.sync += [
                    self._cons_lo.status.eq(self.consumer.pos[:8]),
                    self._cons_hi.status.eq(self.consumer.pos[8:]),
                    self._prod_lo.status.eq(self.producer.produce_write.v[:8]),
                    self._prod_hi.status.eq(self.producer.produce_write.v[8:]),
                    self._prod_hd_lo.status.eq(self.producer.produce_header.v[:8]),
                    self._prod_hd_hi.status.eq(self.producer.produce_header.v[8:]),

                    self._size_lo.status.eq(self.producer.size.v[:8]),
                    self._size_hi.status.eq(self.producer.size.v[8:]),
                    self._cons_status.status[0].eq(self.consumer.busy),
                    #self._prod_state.status.eq(self.producer.fsm.state),

                    If(self.producer.out_addr.stb & self.producer.out_addr.ack,
                        self._last_start_lo.status.eq(self.producer.out_addr.payload.start[:8]),
                        self._last_start_hi.status.eq(self.producer.out_addr.payload.start[8:]),
                        self._last_count_lo.status.eq(self.producer.out_addr.payload.count[:8]),
                        self._last_count_hi.status.eq(self.producer.out_addr.payload.count[8:]),
                        self._last_pw_lo.status.eq(self.producer.produce_write.v[:8]),
                        self._last_pw_hi.status.eq(self.producer.produce_write.v[8:]),
                        )
                    ]

class TestWhacker(Module):
    
    def __init__(self):
        from migen.actorlib.sim import SimActor, Dumper, Token
        def packet(size=0, st=0, end=1):
            yield  Token('source', {'rxcmd':1, 'd':0x40})
            for i in range(size):
                yield  Token('source', {'rxcmd':0, 'd':(i+st)&0xFF})
            
            if end != 4:
                yield  Token('source', {'rxcmd':1, 'd':0x40 | end})

            print("Complete")

        def gen():
            for i in packet(530, 0, 1):
                yield i

            for i in packet(530, 0x10, 1):
                yield i

            for i in packet(10, 0x20, 4):
                yield i
            
            for i in packet(10, 0x30, 2):
                yield i

        class SimSource(SimActor):
            def __init__(self):
                self.source = Endpoint(ULPI_DATA_D)
                SimActor.__init__(self, gen())
    
        self.submodules.w = Whacker(2048)

        self.submodules.src = SimSource()
        self.comb += self.src.source.connect(self.w.sink)
        self.comb += self.src.busy.eq(0)

        self.submodules.dmp = Dumper(D_LAST)
        self.comb += self.w.source.connect(self.dmp.result)
        self.comb += self.dmp.busy.eq(0)


if __name__ == '__main__':
    from migen.sim.generic import Simulator, TopLevel
    from migen.sim.icarus import Runner
    tl = TopLevel("testwhacker.vcd")
    tl.clock_domains[0].name_override='sys_clk'
    test = TestWhacker()
    sim = Simulator(test, tl, Runner(keep_files=True))
    sim.run(2000)
    

