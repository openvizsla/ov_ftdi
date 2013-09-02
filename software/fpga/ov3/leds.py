from migen.fhdl.std import *
from migen.fhdl import verilog
from migen.genlib.cdc import MultiReg
from migen.bank import description, csrgen
from migen.bus.csr import Initiator, Interconnect
from migen.bus.transactions import *
from migen.sim.generic import Simulator

class LED_outputs(Module, description.AutoCSR):
    def __init__(self, leds):
        self._out = description.CSRStorage(flen(leds), atomic_write=True)

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
