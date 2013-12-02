from migen.fhdl.std import *
from sim.test_sdramctl import TestSDRAMComplex
from sdram_bist import SdramBist
import unittest

class BISTTester(Module):
    def __init__(self, unit):
        self.submodules.ctl = TestSDRAMComplex()
        self.submodules.master = SdramBist(self.ctl.hostif, 3000)

        self.gen = self.__gen()
        self.unit = unit

    def __gen(self):

        for pat in range(0, 6):
            yield
            yield
            yield
            self.s.wr(self.master.start, 1)
            self.s.wr(self.master.sel_test, pat)

            while not self.s.rd(self.master.busy):
                yield
            self.s.wr(self.master.start, 0)

            while self.s.rd(self.master.busy):
                yield

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


class SDRAMSingleMasterTests(unittest.TestCase):
    def __run_gen(self, n=35000):
        from migen.sim import icarus
        from migen.sim.generic import Simulator, TopLevel

        import os.path

        SDRAM_MODEL="sim/mt48lc16m16a2.v"

        if not os.path.exists(SDRAM_MODEL):
            raise ValueError("Please download and save the vendor sdram model in %s (not redistributable)" % SDRAM_MODEL)

        runner = icarus.Runner(extra_files=["sim/mt48lc16m16a2.v"], keep_files=1)
        args = []
        args += ["sdramctl.vcd"]

        tl = TopLevel(*args, vcd_level=0)
        test = BISTTester(self)


        sim = Simulator(test, tl, runner)
        sim.run(n)


    def testX(self):
        self.__run_gen()

