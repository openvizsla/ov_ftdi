#!/usr/bin/env python3

from migen.fhdl.std import *
import ov3

plat = ov3.Platform()

class OV3(Module):
    def __init__(self):
        led1 = plat.request("led")
        led2 = plat.request("led")
        led3 = plat.request("led")
        counter = Signal(26)
        self.comb += led1.eq(~counter[25])
        self.comb += led2.eq(~counter[24])
        self.comb += led3.eq(~counter[23])
        self.sync += counter.eq(counter + 1)

if __name__ == "__main__":
    plat.build_cmdline(OV3())
