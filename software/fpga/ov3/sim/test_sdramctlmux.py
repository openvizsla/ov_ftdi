from migen.fhdl.std import *
from sim.test_sdramctl import M, TestSDRAMComplex, TestMaster
from ovhw.sdram_mux import SdramMux
import unittest

class MultiMasterTester(Module):
    def __init__(self, gens):
        self.submodules.ctl = TestSDRAMComplex()
        self.submodules.mux = SdramMux(self.ctl.hostif)

        self.masters = []
        for n, gen in enumerate(gens):
            port = self.mux.getPort()
            master = TestMaster(port, gen, stop_on_finish=False)
            self.masters.append(master)
            setattr(self.submodules, "host_%d" % n, master)

    def do_simulation(self, s):
        if all(m.complete for m in self.masters):
            s.interrupt = 1



class SDRAMMultiMasterTests(unittest.TestCase):
    def __run_gen(self, gens, n=25000):
        from migen.sim import icarus
        from migen.sim.generic import Simulator, TopLevel

        runner = icarus.Runner(extra_files=["sim/mt48lc16m16a2.v"])
        args = []
        #args += ["sdramctl.vcd"]

        tl = TopLevel(*args, vcd_level=0)

        def wrap(gg):
            def _gen(test):
                gl = gg
                if not isinstance(gl, list):
                    gl = [gl]

                for g in gl:
                    yield from g(test)
                test.complete = True

            return _gen

        
        test = MultiMasterTester(wrap(i) for i in gens)

        # Inject complete variable thats monitored
        for m in test.masters:
            m.complete = False

        sim = Simulator(test, tl, runner)
        sim.run(n)

        # Test ran to completion
        self.assertTrue(all(m.complete for m in test.masters))

    def __create_rw_txn(self, s, l):
        def gen(test):
            yield from test.write_txn(s, range(0, l))
            res = yield from test.read_txn(s, l)

            self.assertEqual(res, list(range(0, l)))
        return gen

    def __create_overlap_txn(self, s, l):
        def gen(test):
            yield from test.write_txn(s, [0xCAFE] * l)
            yield from test.write_txn(s + 1, range(s+1, s + l - 1) )
            res = yield from test.read_txn(s, l)

            self.assertEqual(res, 
                [0xCAFE] + list(range(s+1, s+l-1)) + [0xCAFE])
        return gen

    def __create_b2b_read_txn(self, s, l):
        def gen(test):
            yield from test.write_txn(s, range(l))
            res1 = yield from test.read_txn(s, l//2)
            res2 = yield from test.read_txn(s+l//2, l//2)

            self.assertEqual(res1, list(range(l//2)))
            self.assertEqual(res2, list(range(l//2,l)))
        return gen

    def __wait(self, n):
        def gen(test):
            for i in range(0, n):
                yield
        return gen
        
    def testBytes0(self):
        self.__run_gen(
            [
                [
                    self.__create_rw_txn(0, 128), 
                    self.__create_rw_txn(800, 10), 
                    self.__create_rw_txn(900, 10), 
                ],
                [
                    self.__create_rw_txn(128,128),
                    self.__wait(1000),
                    self.__create_rw_txn(700,10),
                ],
                self.__create_rw_txn(256, 128),
                self.__create_rw_txn(256+128,128),    
            ])

    def testBytesEndOfMem(self):
        self.__run_gen([
            self.__create_rw_txn(480, 50),
            self.__create_rw_txn(480+512, 50)
            ])

    def testWriteTermination(self):
        self.__run_gen([
            self.__create_overlap_txn(80,100),
            self.__create_overlap_txn(80+512,100),
            ])

    def testWriteEOMTermination(self):
        self.__run_gen([
            self.__create_overlap_txn(500,13),
            self.__create_overlap_txn(1012, 13)
            ])

    def testBackBackReads(self):
        self.__run_gen([
            self.__create_b2b_read_txn(0,128),
            self.__create_b2b_read_txn(512,128)
        ])

    def testBackBackReadsOVL(self):
        self.__run_gen([
            self.__create_b2b_read_txn(512-64,128),
            self.__create_b2b_read_txn(1024-64,128)
        ])
if __name__ == "__main__":
    unittest.main()
     
