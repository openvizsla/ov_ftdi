#!/usr/bin/env python3

from migen.fhdl.std import *
import ov3, clocking
from sdram import SDRAMFIFO
from migen.genlib.cdc import NoRetiming, MultiReg


plat = ov3.Platform()

class OV3(Module):
    def __init__(self):
        clk_ref = plat.request("clk50")
        self.submodules.clockgen = clocking.ClockGen(clk_ref)
        self.clock_domains.cd_sys = self.clockgen.cd_sys
        self.clock_domains.cd_c33 = self.clockgen.cd_c33

        led1 = plat.request("led", 1)
        led2 = plat.request("led", 2)
        led3 = plat.request("led", 3)
        btn = plat.request("btn")

        # Synchronize button to sys clock domain (and invert while we're at it)
        btn_sync = Signal()
        self.specials += [
            NoRetiming(btn),
            MultiReg(~btn, btn_sync, "sys")
        ]

        self.submodules.sdram = RenameClockDomains(
            SDRAMFIFO(plat.request("sdram"),
                      clk_out=self.clockgen.clk_sdram,
                      clk_sample=self.clockgen.clk_sdram_sample,
                      databits=16, rowbits=13, colbits=9, bankbits=2,
                      inbuf=1024, outbuf=1024, burst=512,
                      tRESET=20000, tCL=3, tRP=4, tRFC=12, tRCD=4,
                      tREFI=780),
            {"read": "sys", "write": "c33"})

        # Test the SDRAM: write incrementing 16-bit words
        # Do this at 33MHz
        word_ctr = Signal(23)
        self.sync.c33 += If(self.sdram.writable & self.sdram.we,
                            word_ctr.eq(word_ctr + 1))
        self.comb += [
            self.sdram.we.eq(1),
            self.sdram.din.eq(word_ctr[:16]),
            led1.eq(~word_ctr[22])
        ]

        # Read back what was written and check for errors
        # Do this at 100MHz (limited by SDRAM timesliced bandwidth)
        word_ctr2 = Signal(23)
        valid = Signal(reset=1)
        self.sync += If(self.sdram.readable & self.sdram.re,
                        word_ctr2.eq(word_ctr2 + 1),
                        If(self.sdram.dout != word_ctr2[:16],
                           valid.eq(0)))
        self.comb += [
            self.sdram.re.eq(~btn_sync),
            led2.eq(~word_ctr2[22]),
            led3.eq(~valid),
        ]

if __name__ == "__main__":
    plat.build_cmdline(OV3())
