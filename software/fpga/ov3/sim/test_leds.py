from migen.fhdl.std import *
from migen.bus.csr import Initiator, Interconnect
from migen.sim.generic import Simulator
from migen.bus.transactions import *
from migen.bank import csrgen

from ovhw.leds import LED_outputs
from sim.util import TIProxy

import unittest


class TB(Module):
    def __init__(self):
        self.prx = TIProxy()

        self.l_0_ovr = Signal()
        self.leds_v = Signal(3)
        self.submodules.leds = LED_outputs(self.leds_v, [[self.l_0_ovr], [0], [1]])
        self.submodules.ini = Initiator(self.prx._ini_iterator())
        self.submodules.ba = csrgen.BankArray(self, lambda name, _: 0)
        self.submodules.incon = Interconnect(self.ini.bus, self.ba.get_buses())

        self._gen = None

    def setGen(self, gen):
        self._gen = gen

    def do_simulation(self, s):
        self.s = s

        try:
            next(self._gen)
        except StopIteration:
            s.interrupt = True


class LEDTests(unittest.TestCase):
    def setUp(self):
        self.tb = TB()
        self.sim = Simulator(self.tb)

    def _run(self):
        with self.sim as sim:
            sim.run()

    def test__write_direct(self):
        def gen():
            self.tb.prx.issue(TWrite(0, 0x7))
            yield from self.tb.prx.wait()
            lv = self.tb.s.rd(self.tb.leds_v)
            self.tb.prx.fini()

            self.assertEqual(lv, 7)

        self.tb.setGen(gen())

        self._run()

    def test_muxes_1(self):
        def gen():
            # Set muxes
            self.tb.prx.issue(TWrite(1, 1))
            self.tb.prx.issue(TWrite(2, 1))
            self.tb.prx.issue(TWrite(3, 1))

            yield from self.tb.prx.wait()

            # Test that the MUX worked
            lv = self.tb.s.rd(self.tb.leds_v)
            self.assertEqual(lv, 0x4)

            # Test changing an LED results in writing to the mux
            self.tb.s.wr(self.tb.l_0_ovr, 1)
            yield
            self.assertEqual(self.tb.s.rd(self.tb.leds_v), 5)
            
            # Test partial mux
            self.tb.prx.issue(TWrite(3,0))
            yield from self.tb.prx.wait()
            self.assertEqual(self.tb.s.rd(self.tb.leds_v), 1)

            self.tb.prx.issue(TWrite(0,0x4))
            yield from self.tb.prx.wait()
            self.assertEqual(self.tb.s.rd(self.tb.leds_v), 0x5)

        self.tb.setGen(gen())
        self._run()


if __name__ == "__main__":
    unittest.main()

