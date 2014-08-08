from migen.fhdl.std import *
from ovhw.sdram_mux import SDRAMMux
from sim.util import par, gather_files
import unittest
import sim.sdram_test_util
from ovhw.sdram_host_read import SDRAM_Host_Read
import os
from migen.sim import icarus
from migen.sim.generic import Simulator, TopLevel

class TestBench(Module):
    def __init__(self, sdram_modname):
        self.submodules.cpx = sim.sdram_test_util.TestSDRAMComplex(sdram_modname)
        self.submodules.mux = SDRAMMux(self.cpx.hostif)
        hostif = self.mux.getPort()
        self.submodules.sdramhostread = SDRAM_Host_Read(hostif)
        
        self.hostif = hostif
        self.wait_for_i = False
        
        self.sync += self.sdramhostread.source.ack.eq(1)

    def do_simulation(self, selfp):
        if selfp.hostif.i_stb:
            self.wait_for_i = True
        if selfp.hostif.i_ack:
            self.wait_for_i = False
        if selfp.hostif.d_stb and self.wait_for_i:
            print("cycle %d %d %02x %d" % (selfp.simulator.cycle_counter, selfp.sdramhostread.source.stb, selfp.sdramhostread.source.payload.d, selfp.sdramhostread.source.payload.last))
        if selfp.simulator.cycle_counter == 1000:
            selfp.sdramhostread._go.storage = 1
#        if selfp.simulator.cycle_counter == 8000:
#            selfp.sdramhostread._go.storage = 0

class SDRAMHostReadTest(sim.sdram_test_util.SDRAMUTFramework, unittest.TestCase):
    def setUp(self):
        self.tb = TestBench("mt48lc16m16a2")
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

    def _run(self):
        with self.sim:
            self.sim.run(100000)
    
    def test_sdramhostread(self):
        self._run()

if __name__ == "__main__":
    unittest.main()
     
