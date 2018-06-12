from migen import *
from misoc.interconnect.csr import AutoCSR, CSRStorage
from itertools import zip_longest

# Basic programmable LED module
class LED_outputs(Module, AutoCSR):

    def __init__(self, leds_raw, leds_muxes=None, active=1):
        """
        leds_raw: output IOs for the LEDs
        leds_muxes: internal digital signals that could feed a LED
        """


        leds = Signal(len(leds_raw))

        # Register containing the desired LED status
        self._out = CSRStorage(len(leds), atomic_write=True)

        # For each LED, we generate a MUX register.
        # The MUX register can connect either the bit in the 'output' register or
        # signals supplied via led_muxes

        if leds_muxes:
            assert len(leds_muxes) == len(leds)
            for n in range(len(leds)):
                name = "mux_%d" % n
                attr = CSRStorage(8, atomic_write=True, name=name)
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
