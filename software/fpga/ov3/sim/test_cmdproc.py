import unittest

from migen import *
from migen.sim import run_simulation

from ovhw.dummy_source import DummySource

class TestBench(Module):
    def __init__(self):
        from ovhw.cmdproc import CmdProc
        class ff:
            def __getattr__(self, attrname):
                if not attrname in self.__dict__:
                    self.__dict__[attrname] = ff()

                return self.__dict__[attrname]


        self.ff = ff()

        self.ff.incoming_fifo.re = Signal(name="FIFOI_re")
        self.ff.incoming_fifo.readable = Signal(reset=0, name="FIFOI_readable")
        self.ff.incoming_fifo.dout = Signal(8, name="FIFOI_dout")

        self.ff.output_fifo.we = Signal()
        self.ff.output_fifo.writable = Signal(reset=1)
        self.ff.output_fifo.din = Signal(8)
        
        self.submodules.dummy0 = DummySource(0xE0)
        self.submodules.dummy1 = DummySource(0xE8)
        
        self.submodules.cm = self.cm = CmdProc(self.ff, [self.dummy0, self.dummy1])
    

    def do_simulation(self, selfp):
        self.selfp = selfp


class TestCmdproc(unittest.TestCase):
    def setUp(self):
        self.tb = TestBench()

    def test_cmdproc(self):
        write_transactions = []

        def collector():
            yield "passive"
            while 1:
                if (yield self.tb.cm.master.we):
                    write_transactions.append(((yield self.tb.cm.master.adr), (yield self.tb.cm.master.dat_w)))
                yield

        def do_outbound_fifo_rd(o):
            yield o.writable.eq(1)
            while (yield o.we) == 0:
                yield 

            v = yield o.din
            yield o.writable.eq(0)
            return v


        def do_income_fifo_wr(o, v):
            yield o.readable.eq(1)
            yield o.dout.eq(v)

            while (yield o.re) == 0:
                yield
            
            yield
            yield o.readable.eq(0)

        def gen():
            for i in range(5):
                yield 

            yield from do_income_fifo_wr(self.tb.ff.incoming_fifo, 0x55)
            yield from do_income_fifo_wr(self.tb.ff.incoming_fifo, 0x92)
            yield from do_income_fifo_wr(self.tb.ff.incoming_fifo, 0x34)
            yield from do_income_fifo_wr(self.tb.ff.incoming_fifo, 0x56)
            yield from do_income_fifo_wr(self.tb.ff.incoming_fifo, 0xAA)

            for i in range(10):
                yield 

            self.assertEqual(write_transactions, [(0x1234, 0x56)])


        self.sim = run_simulation(self.tb, [gen(), collector()], vcd_name="test_cmdproc.vcd")


if __name__ == '__main__':
    unittest.main()
        
