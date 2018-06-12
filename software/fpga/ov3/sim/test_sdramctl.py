import unittest
from migen import *
import sim.sdram_test_util

class SDRAMSingleTester(sim.sdram_test_util.SDRAMUTFramework):
    class TestBench(Module):
        def __init__(self, sdram_modname):
            self.submodules.ctl = sim.sdram_test_util.TestSDRAMComplex(sdram_modname)
            self.submodules.master = sim.sdram_test_util.TestMaster(self.ctl.hostif)

    def setUp(self):
        self.tb = self.TestBench(self.SDRAM_MODNAME)
        self.master = self.tb.master
        self._inner_setup()

    def _run_with(self, gen, n=5000):
        self.tb.master.setSeq(gen(self.tb.master))

        with self.sim as sim:
            sim.run(n)
        
    def tearDown(self):
        self.assertTrue(self.master.complete)


class SDRAMSingleMasterTests:
    def testBytes0(self):
        self._run_with(self._rw(0, 128))

    def testBytesEndOfMem(self):
        self._run_with(self._rw(480, 50))

    def testWriteTermination(self):
        self._run_with(self._overlap(80,100))

    def testWriteEOMTermination(self):
        self._run_with(self._overlap(500,13))

    def testBackBackReads(self):
        self._run_with(self._b2b_read(0,128))

    def testBackBackReadsOVL(self):
        self._run_with(self._b2b_read(512-64,128))

# For now need to instantiate these manually
# We should automatically create tests for all of the known SDRAM types
class SDRAMSingleMasterTests_mt48lc16m16a2(SDRAMSingleMasterTests,
                                           sim.sdram_test_util.SDRAMTestSequences,
                                           SDRAMSingleTester,
                                           unittest.TestCase):
        SDRAM_MODNAME = "mt48lc16m16a2"

if __name__ == "__main__":
    unittest.main()
