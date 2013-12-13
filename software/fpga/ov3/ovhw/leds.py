from migen.fhdl.std import *
from migen.bank import description
from itertools import zip_longest

class LED_outputs(Module, description.AutoCSR):
    def __init__(self, leds_raw, leds_muxes=None, active=1):

        leds = Signal(flen(leds_raw))

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

        self.comb += [
            leds_raw.eq(leds if active else ~leds)
        ]
