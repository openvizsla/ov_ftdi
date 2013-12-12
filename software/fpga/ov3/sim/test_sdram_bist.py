from migen.fhdl.std import *
from sim.sdram_test_util import TestSDRAMComplex, SDRAMUTFramework
import ovhw.sdram_bist
import unittest

class BISTTester(Module):
    def __init__(self, unit, sdram_modname):
        self.submodules.ctl = TestSDRAMComplex(sdram_modname)
        self.submodules.master = ovhw.sdram_bist.SDRAMBIST(self.ctl.hostif,
                                                           3000)

        self.gen = self.__gen()
        self.unit = unit

        self.pat = 0

    def __gen(self):

        yield from (None for _ in range(3))
        self.s.wr(self.master.start, 1)
        self.s.wr(self.master.sel_test, self.pat)

        while not self.s.rd(self.master.busy): yield

        self.s.wr(self.master.start, 0)

        while self.s.rd(self.master.busy): yield

        yield
        self.unit.assertTrue(self.s.rd(self.master.ok))

        self.s.interrupt = 1

    def do_simulation(self, s):
        self.s = s
        try:
            if (self.gen):
                next(self.gen)
        except StopIteration:
            self.gen = None


class SDRAMBISTTests(
    SDRAMUTFramework,
    unittest.TestCase):

    def setUp(self):
        self.tb = BISTTester(self, "mt48lc16m16a2")
        self._inner_setup()

# Inject BIST testcases based on defined BIST enums
for tname in dir(ovhw.sdram_bist):
    if not tname.startswith("TEST_"):
        continue

    tno = getattr(ovhw.sdram_bist, tname)

    def closure():
        _tno = tno
        def testfn(self, n=35000):
            self.tb.pat = _tno
            with self.sim as sim:
                sim.run(35000)
        return testfn

    setattr(SDRAMBISTTests, 
            "test_%s" % tname.replace("TEST_",""),
            closure())
