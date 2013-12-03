from migen.fhdl.std import *
from migen.fhdl import verilog
from migen.genlib.cdc import MultiReg
from migen.bank import description, csrgen
from migen.bus.csr import Initiator, Interconnect
from migen.bus.transactions import *
from migen.sim.generic import Simulator

from itertools import zip_longest

class LED_outputs(Module, description.AutoCSR):
    def __init__(self, leds, leds_muxes=None):

        self._out = description.CSRStorage(flen(leds), atomic_write=True)

        if leds_muxes:
            assert len(leds_muxes) == flen(leds)
            for n in range(flen(leds)):
                name = "mux_%d" % n
                attr = description.CSRStorage(8, atomic_write=True, name=name)
                setattr(self, "_%s" % name, attr)

                mux_vals = [self._out.storage[n]]

                if leds_muxes[n]:
                    mux_vals.extend(leds_muxes[n])

                cases = {k: leds[n].eq(v) for k, v in enumerate(mux_vals)}

                self.comb += [
                        leds[n].eq(0),
                        Case(attr.storage, cases)
                        ]


        else:
            self.comb += [
                leds.eq(self._out.storage),
            ]

def my_gen():
    for x in range(10):
        t = TWrite(0, x)
        yield t

class TB(Module):
    def __init__(self):
        self.leds_v = Signal(3)
        self.submodules.leds = LED_outputs(self.leds_v)
        self.submodules.ini = Initiator(my_gen())
        self.submodules.incon = Interconnect(self.ini.bus, [self.leds.bank.bus])

    def do_simulation(self, s):
        s.interrupt = self.ini.done

        print ("%8d %x" % (s.cycle_counter, s.rd(self.leds_v)))



def main():
    tb = TB()
    sim = Simulator(tb)
    sim.run()

if __name__ == "__main__":

    main()
