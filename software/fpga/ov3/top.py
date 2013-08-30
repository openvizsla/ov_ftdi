#!/usr/bin/env python3

from migen.fhdl.std import *
import ov3, clocking
from sdram import SDRAMFIFO
from ulpi import ULPI, ULPI_BUS, ULPI_REG, ULPI_DATA, ULPIRegTest
from migen.genlib.cdc import NoRetiming, MultiReg
from migen.genlib.record import Record


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
        
        # ULPI
        
        ulpi_bus = Record(ULPI_BUS)
        ulpi_reg = Record(ULPI_REG)
        ulpi_data = Record(ULPI_DATA)

        self.clock_domains.cd_ulpi = ClockDomain()

        self.cd_ulpi.clk = ulpi_bus.clk
        self.cd_ulpi.rst = ulpi_bus.rst
        
        ulpi_pins = plat.request("ulpi")
        
        self.comb += ulpi_pins.rst.eq(~ulpi_bus.rst)
        self.comb += ulpi_bus.nxt.eq(ulpi_pins.nxt)
        self.comb += ulpi_bus.clk.eq(ulpi_pins.clk)
        self.comb += ulpi_bus.dir.eq(ulpi_pins.dir)
        self.comb += ulpi_pins.stp.eq(ulpi_bus.stp)
        dq = TSTriple(8)
        self.specials += dq.get_tristate(ulpi_pins.d)
        self.comb += ulpi_bus.di.eq(dq.i)
        self.comb += dq.o.eq(ulpi_bus.do)
        self.comb += dq.oe.eq(ulpi_bus.doe)
        
        self.submodules.ulpi = RenameClockDomains(
          ULPI(ulpi_bus, ulpi_reg, ulpi_data),
          {"sys": "ulpi"}
        )
        
        self.clock_domains.cd_ulpi_reg = ClockDomain()
        self.cd_ulpi_reg.clk = self.cd_sys.clk
        self.cd_ulpi_reg.rst = ulpi_bus.rst

        self.submodules.regtest = RenameClockDomains(
          ULPIRegTest(ulpi_reg),
          {"sys":"ulpi_reg"}
        )
        
        self.comb += ulpi_bus.rst.eq(btn_sync)

if __name__ == "__main__":
    plat.build_cmdline(OV3())
