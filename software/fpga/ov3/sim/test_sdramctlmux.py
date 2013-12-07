from migen.fhdl.std import *
from ovhw.sdram_mux import SdramMux
import unittest
import sim.sdram_test_util

class SDRAMMultiTester(sim.sdram_test_util.SDRAMUTFramework):
    class TestBench(Module):
        """ 
        Test module consisting of the Emulated SDRAM + Controller complex, and an
        SDRAM mux.

        For each generator passed as an argument, a master will be created and
        attached to the SDRAM mux
        """
        def __init__(self, sdram_modname):
            self.submodules.cpx = sim.sdram_test_util.TestSDRAMComplex(sdram_modname)
            self.submodules.mux = SdramMux(self.cpx.hostif)

            self.complete = False

            # Create and attach the masters
            self.masters = []

        def bind(self, gen):
            master = sim.sdram_test_util.TestMaster(
                self.mux.getPort(), stop_on_finish=False)
            master.setSeq(gen(master))

            self.masters.append(master)
            setattr(self.submodules, "master_%d" % len(self.masters), master)

        def do_simulation(self, s):
            # Finalize simulation when all masters have run to completion
            self.complete = all(m.complete for m in self.masters)
            if self.complete:
                s.interrupt = 1


    def setUp(self):
        self.tb = self.TestBench(self.SDRAM_MODNAME)

    def _run_gen(self, gens, n=25000):
        # wrapper function that calls a series of generators
        # in sequence while binding masters through
        def wrap(gl):
            if not isinstance(gl, list):
                gl = [gl]

            return lambda master: (g(master) for g in gl)

        for gen in gens:
            self.tb.bind(wrap(gen))

        # We defer the inner setup to here as the fragment emitted will
        # depend on how many master generators we're using
        self._inner_setup()

        with self.sim as sim:
            sim.run(n)

    def tearDown(self):
        # Test ran to completion
        self.assertTrue(all(m.complete for m in self.tb.masters))
        

class SDRAMMultiMasterTests:
    def testBytes0(self):
        self._run_gen(
            [
                [
                    self._rw(0, 128), 
                    self._rw(800, 10), 
                    self._rw(900, 10), 
                ],
                [
                    self._rw(128,128),
                    self._wait(1000),
                    self._rw(700,10),
                ],
                self._rw(256, 128),
                self._rw(256+128,128),    
            ])

    def testBytesEndOfMem(self):
        self._run_gen([
            self._rw(480, 50),
            self._rw(480+512, 50)
            ])

    def testWriteTermination(self):
        self._run_gen([
            self._overlap(80,100),
            self._overlap(80+512,100),
            ])

    def testWriteEOMTermination(self):
        self._run_gen([
            self._overlap(500,13),
            self._overlap(1012, 13)
            ])

    def testBackBackReads(self):
        self._run_gen([
            self._b2b_read(0,128),
            self._b2b_read(512,128)
        ])

    def testBackBackReadsOVL(self):
        self._run_gen([
            self._b2b_read(512-64,128),
            self._b2b_read(1024-64,128)
        ])

class SDRAMMuxTests_mt48lc16m16a2(SDRAMMultiMasterTests,
                                  sim.sdram_test_util.SDRAMTestSequences,
                                  SDRAMMultiTester,
                                  unittest.TestCase):
    SDRAM_MODNAME = "mt48lc16m16a2"

if __name__ == "__main__":
    unittest.main()
     
