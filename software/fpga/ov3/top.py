#!/usr/bin/env python3

from migen.fhdl.std import *
import ov3, clocking
from sdram import SDRAMFIFO


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
            led3.eq(~self.clockgen.cd_sys.rst),
        ]
        self.sync += counter.eq(counter + 1)

        self.submodules.sdram = RenameClockDomains(
            SDRAMFIFO(plat.request("sdram"),
                      clk_out=self.clockgen.clk_sdram,
                      clk_sample=self.clockgen.clk_sdram_sample,
                      databits=16, rowbits=13, colbits=9, bankbits=2,
                      inbuf=1024, outbuf=1024, burst=512,
                      tRESET=20000, tCL=3, tRP=4, tRFC=12, tRCD=4,
                      tREFI=780),
            {"read": "sys", "write": "sys"})


if __name__ == "__main__":
    plat.build_cmdline(OV3())
