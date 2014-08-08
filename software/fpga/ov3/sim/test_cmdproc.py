import unittest

from migen.fhdl.std import *
from migen.fhdl.bitcontainer import bits_for
from migen.flow.actor import Source, Sink
from migen.actorlib.sim import SimActor, Dumper, Token
from migen.sim.generic import Simulator, TopLevel

from ovhw.ov_types import ULPI_DATA_TAG

from ovhw.constants import *
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

        self.ff.incoming_fifo.re = Signal()
        self.ff.incoming_fifo.readable = Signal(reset=0)
        self.ff.incoming_fifo.dout = Signal(8)

        #self.sync += self.ff.incoming_fifo.readable.eq(0)
        #self.sync += self.ff.incoming_fifo.dout.eq(0)

        self.ff.output_fifo.we = Signal()
        self.ff.output_fifo.writable = Signal(reset=1)
        self.ff.output_fifo.din = Signal(8)
        
        self.submodules.dummy0 = DummySource(0xE0)
        self.submodules.dummy1 = DummySource(0xE8)
        
        self.submodules.cm = CmdProc(self.ff, [self.dummy0, self.dummy1])
    

    def do_simulation(self, selfp):
        self.selfp = selfp
    
class TestCmdproc(unittest.TestCase):
    def setUp(self):
        self.tb = TestBench()
        vcd = None
        vcd = "test_cmdproc.vcd"
        self.sim = Simulator(self.tb, TopLevel(vcd, vcd_level = 3))

    def _run(self):
        with self.sim as sim:
            sim.run(400)

    def test_cmdproc(self):
        self._run()


if __name__ == '__main__':
    unittest.main()
        
