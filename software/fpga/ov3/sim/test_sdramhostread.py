from migen import *
from ovhw.sdram_mux import SDRAMMux
from sim.util import par, gather_files
import unittest
import sim.sdram_test_util
from ovhw.sdram_host_read import SDRAM_Host_Read
from ovhw.sdram_sink import SDRAM_Sink
from ovhw.dummy_source import DummySource
import os
from migen.sim import icarus
from migen.sim.generic import Simulator, TopLevel

class TestBench(Module):
    def __init__(self, sdram_modname, dummy_data, dummy_idle, max_burst_length, host_burst_length):
        self.submodules.cpx = sim.sdram_test_util.TestSDRAMComplex(sdram_modname)
        self.submodules.mux = SDRAMMux(self.cpx.hostif)
        hostif = self.mux.getPort()
        self.submodules.sdram_host_read = SDRAM_Host_Read(hostif, host_burst_length)
        self.host_burst_length = host_burst_length
        
        self.hostif = hostif
        self.wait_for_i = False
        
        self.sync += self.sdram_host_read.source.ack.eq(1)
        
        self.hostif_sink = self.mux.getPort()

        self.submodules.dummy0 = DummySource(0xe0, dummy_data, dummy_idle)
        self.submodules.sdram_sink = SDRAM_Sink(self.hostif_sink, max_burst_length)

        self.comb += self.sdram_host_read.wptr.eq(self.sdram_sink.wptr)
        self.comb += self.sdram_sink.rptr.eq(self.sdram_host_read.rptr)
        self.comb += self.dummy0.source.connect(self.sdram_sink.sink)
        
        def expected():
            while True:
                yield 0xE0
                yield 0xE1
                for i in range(301):
                    yield i & 0xFF
        
        self.exp = expected()
        self.pkt = []
    
    def do_simulation(self, selfp):
        if selfp.hostif.i_stb:
            self.wait_for_i = True
        if selfp.hostif.i_ack:
            self.wait_for_i = False
#        if selfp.hostif.d_stb and self.wait_for_i:
        if selfp.sdram_host_read.source.stb:
#            print("cycle %d %d %02x %d" % (selfp.simulator.cycle_counter, selfp.sdram_host_read.source.stb, selfp.sdram_host_read.source.payload.d, selfp.sdram_host_read.source.payload.last))
            self.pkt.append(selfp.sdram_host_read.source.payload.d)
            assert selfp.sdram_host_read.source.payload.last == (len(self.pkt) == self.host_burst_length * 2 + 1)
            
            if selfp.sdram_host_read.source.payload.last:
                print(self.pkt)
                assert self.pkt[0] == 0xD0
                for r in self.pkt[1:]:
                    n = next(self.exp)
                    assert r == n, "expected %02x, read %02x in %r" % (n, r, self.pkt)
                self.pkt = []
            
        if selfp.simulator.cycle_counter == 1000:
            ring_start = 1*1024*1024
            ring_end = ring_start + 1024
            selfp.sdram_host_read._ring_base.storage = ring_start
            selfp.sdram_host_read._ring_end.storage = ring_end
            selfp.sdram_host_read._go.storage = 1
            selfp.sdram_sink._ring_base.storage = ring_start
            selfp.sdram_sink._ring_end.storage = ring_end
            selfp.sdram_sink._go.storage = 1
#        if selfp.simulator.cycle_counter == 8000:
#            selfp.sdram_host_read._go.storage = 0

class SDRAMHostReadTest(sim.sdram_test_util.SDRAMUTFramework, unittest.TestCase):
#    def setUp(self):

    def _run(self, dummy_data, dummy_idle, max_burst_length, host_burst_length):
        self.tb = TestBench("mt48lc16m16a2", dummy_data, dummy_idle, max_burst_length, host_burst_length)
        # Verify that all necessary files are present
        files = gather_files(self.tb)
        for i in files:
            if not os.path.exists(i):
                raise FileNotFoundError("Please download and save the vendor "
                                        "SDRAM model in %s (not redistributable)"
                                        % i)

        runner = icarus.Runner(extra_files=files)
        vcd = "test_%s.vcd" % self.__class__.__name__
        self.sim = Simulator(self.tb, TopLevel(vcd), sim_runner=runner) 
        with self.sim:
            self.sim.run(10000)
    
    def test_sdram_host_read(self):
        self._run(300, 1000, 256, 16)

    def test_sdram_host_read_2(self):
        self._run(300, 10, 256, 256)

    def test_sdram_host_read_3(self):
        self._run(300, 1000, 16, 17)

    def test_sdram_host_read_4(self):
        self._run(300, 10, 32, 64)

if __name__ == "__main__":
    unittest.main()
     
