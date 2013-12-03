from migen.fhdl.std import *
from ovhw.sdramctl import SDRAMCTL

class M(Module):
    def __init__(self):
        self.dq = Signal(16)
        self.a = Signal(13)
        self.ba = Signal(2)
        self.dqm = Signal(2)
        self.cke = Signal()
        self.cs_n = Signal()
        self.ras_n = Signal()
        self.cas_n = Signal()
        self.we_n = Signal()
        self.clk = Signal()

        self.specials.pll = Instance("mt48lc16m16a2",
            Instance.InOut("Dq", self.dq),
            Instance.Input("Addr", self.a),
            Instance.Input("Ba", self.ba),
            Instance.Input("Clk", self.clk),
            Instance.Input("Cke", self.cke),
            Instance.Input("Cs_n", self.cs_n),
            Instance.Input("Ras_n", self.ras_n),
            Instance.Input("Cas_n", self.cas_n),
            Instance.Input("We_n", self.we_n),
            Instance.Input("Dqm", self.dqm)
        )


class TestSDRAMComplex(Module):
    def __init__(self):
        self.submodules.sdram = M()
        inv = Signal()
        self.comb += inv.eq(~ClockSignal())

        self.submodules.sdctl = SDRAMCTL(self.sdram,
            inv, inv,
            databits=16, rowbits=13, colbits=9, bankbits=2,
            burst=512, tRESET=200, tCL=3, tRP=4, tRFC=12, tRCD=4,
            tREFI=780, tWR=2)

        self.hostif = self.sdctl.hostif


class TestMaster(Module):
    def __init__(self, hostif, gen, stop_on_finish=True):
        self.hostif = hostif
        self.geninst = gen(self)
        self.stop_on_finish=stop_on_finish

    def __issue(self, addr, wr):
        hostif = self.hostif

        self.s.wr(hostif.i_wr, wr)
        self.s.wr(hostif.i_addr, addr)
        self.s.wr(hostif.i_stb, 1)

        while not self.s.rd(hostif.i_ack):
            yield
        
        self.s.wr(hostif.i_stb, 0)

    def __d_step(self):
        yield
        while (not self.s.rd(self.hostif.d_stb)):
            yield
    
    def write_txn(self, addr, buf):
        assert len(buf) > 0

        hostif = self.hostif

        self.s.wr(hostif.d_write, buf[0])
        self.s.wr(hostif.d_term, 0)

        yield from self.__issue(addr, 1)

        if self.s.rd(hostif.d_stb):
            buf = buf[1:]

        first = 0
        while buf:

            self.s.wr(hostif.d_write, buf[0])
            buf = buf[1:]
            yield from self.__d_step()

        self.s.wr(hostif.d_term, 1)
        yield from self.__d_step()
        self.s.wr(hostif.d_term, 0)

    def read_txn(self, addr, ct):
        hostif = self.hostif
        self.s.wr(hostif.d_term, 0)
        yield from self.__issue(addr, 0)

        buf = []

        while 1:
            if self.s.rd(hostif.d_stb):
                b = self.s.rd(hostif.d_read)
                buf.append(b)
                ct -= 1

                if ct == 0:
                    self.s.wr(hostif.d_term, 1)
                    break

            yield from self.__d_step()

        yield from self.__d_step()
        self.s.wr(hostif.d_term, 0)

        return buf

    def do_simulation(self, s): 
        self.s = s
        if self.geninst:
            try:
                next(self.geninst)
            except StopIteration:
                self.geninst = None
                if self.stop_on_finish:
                    s.interrupt = True
        
class SingleMasterTester(Module):
    def __init__(self, gen):
        self.submodules.ctl = TestSDRAMComplex()
        self.submodules.master = TestMaster(self.ctl.hostif, gen)

import unittest

class SDRAMSingleMasterTests(unittest.TestCase):
    def __run_gen(self, gen, n=5000):
        from migen.sim import icarus
        from migen.sim.generic import Simulator, TopLevel

        import os.path

        SDRAM_MODEL="sim/mt48lc16m16a2.v"

        if not os.path.exists(SDRAM_MODEL):
            raise ValueError("Please download and save the vendor sdram model in %s (not redistributable)" % SDRAM_MODEL)

        runner = icarus.Runner(extra_files=["sim/mt48lc16m16a2.v"])
        args = []
        #args += ["sdramctl.vcd"]

        tl = TopLevel(*args, vcd_level=0)

        def _gen(test):
            x = gen(test)
            yield from x
            test.complete = True

        test = SingleMasterTester(_gen)

        # Inject complete variable thats monitored
        test.master.complete = False

        sim = Simulator(test, tl, runner)
        sim.run(n)

        # Test ran to completion
        self.assertTrue(test.master.complete)

    def __create_rw_txn(self, s, l):
        def gen(test):
            yield from test.write_txn(s, range(s, s+l))
            res = yield from test.read_txn(s, l)

            self.assertEqual(res, list(range(s, s+l)))
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

    def testBytes0(self):
        self.__run_gen(self.__create_rw_txn(0, 128))

    def testBytesEndOfMem(self):
        self.__run_gen(self.__create_rw_txn(480, 50))

    def testWriteTermination(self):
        self.__run_gen(self.__create_overlap_txn(80,100))

    def testWriteEOMTermination(self):
        self.__run_gen(self.__create_overlap_txn(500,13))

    def testBackBackReads(self):
        self.__run_gen(self.__create_b2b_read_txn(0,128))

    def testBackBackReadsOVL(self):
        self.__run_gen(self.__create_b2b_read_txn(512-64,128))

if __name__ == "__main__":
    unittest.main()
    
