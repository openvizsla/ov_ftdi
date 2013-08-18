#!/usr/bin/env python3

from migen.fhdl.std import *
import ov3, clocking

plat = ov3.Platform()

class OV3(Module):
    def __init__(self):
        clk_ref = plat.request("clk50")
        self.submodules.clockgen = clocking.ClockGen(clk_ref)
        self.clock_domains.cd_sys = self.clockgen.cd_sys

        led1 = plat.request("led", 1)
        led2 = plat.request("led", 2)
        led3 = plat.request("led", 3)

        counter = Signal(26)
        self.comb += [
            led1.eq(~counter[25]),
            led2.eq(~counter[24]),
            led3.eq(~self.clockgen.pll_locked),
        ]
        self.sync += counter.eq(counter + 1)

if __name__ == "__main__":
    plat.build_cmdline(OV3())
