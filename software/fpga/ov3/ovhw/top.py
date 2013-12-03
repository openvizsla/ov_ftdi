#!/usr/bin/env python3

from migen.fhdl.std import *
from migen.genlib.cdc import NoRetiming, MultiReg
from migen.genlib.fifo import AsyncFIFO
from migen.genlib.fsm import FSM, NextState
from migen.genlib.record import Record, DIR_M_TO_S
from migen.flow.network import DataFlowGraph, CompositeActor
from migen.flow.actor import Source, Sink
import migen.actorlib.fifo as al_fifo
from migen.bus.csr import Interconnect
from migen.bank.csrgen import BankArray
from migen.bank.description import AutoCSR, CSRStorage, CSRStatus, CSR

import ovhw.clocking as clocking
from ovhw.sdramctl import SDRAMCTL
from ovhw.sdram_mux import SdramMux
from ovhw.sdram_bist import SdramBist
from ovhw.sdrambistcfg import SdramBistCfg
from ovhw.ulpi import ULPI, ULPI_BUS, ULPI_REG, ULPI_DATA
from ovhw.leds import LED_outputs
from ovhw.buttons import BTN_status
from ovhw.whacker.whacker import Whacker
from ovhw.ovf_insert import OverflowInserter
from ovhw.cmdproc import CmdProc
from ovhw.ftdi_bus import FTDI_sync245
from ovhw.ftdi_lfsr_test import FTDI_randtest
from ovhw.ulpicfg import ULPICfg
from ovhw.cfilt import RXCmdFilter

class OV3(Module):
    def __init__(self, plat):
        clk_ref = plat.request("clk50")
        self.submodules.clockgen = clocking.ClockGen(clk_ref)
        self.clock_domains.cd_sys = self.clockgen.cd_sys
        self.clock_domains.cd_c33 = self.clockgen.cd_c33

        led1 = plat.request("led", 1)
        led2 = plat.request("led", 2)
        led3 = plat.request("led", 3)
        btn = plat.request("btn")


        ftdi_io = plat.request("ftdi")
        self.submodules.ftdi_bus = ftdi_bus = FTDI_sync245(self.clockgen.cd_sys.rst,
                ftdi_io)





        # Synchronize button to sys clock domain (and invert while we're at it)
        btn_sync = Signal()
        self.specials += [
            NoRetiming(btn),
            MultiReg(~btn, btn_sync, "sys")
        ]

        self.submodules.sdramctl = SDRAMCTL(plat.request("sdram"),
                      clk_out=self.clockgen.clk_sdram,
                      clk_sample=self.clockgen.clk_sdram_sample,
                      databits=16, rowbits=13, colbits=9, bankbits=2,
                      burst=512,
                      tRESET=20000, tCL=3, tRP=4, tRFC=12, tRCD=4,
                      tREFI=780, tWR=2)

        self.submodules.sdram_mux = SdramMux(self.sdramctl.hostif)

        self.submodules.bist = SdramBist(self.sdram_mux.getPort(), 0x2000000)


        self.submodules.sdram_test = SdramBistCfg(self.bist)

        ######## VALID
        ulpi_bus = Record(ULPI_BUS)
        ulpi_reg = Record(ULPI_REG)

        self.clock_domains.cd_ulpi = ClockDomain()

        cd_rst = Signal()
        self.cd_ulpi.clk = ulpi_bus.clk
        self.cd_ulpi.rst = cd_rst

        # TODO - integrate all below into ULPI module
        ulpi_pins = plat.request("ulpi")
        
        stp_ovr = Signal(1)

        self.comb += ulpi_pins.rst.eq(~ulpi_bus.rst)
        self.comb += ulpi_bus.nxt.eq(ulpi_pins.nxt)
        self.comb += ulpi_bus.clk.eq(ulpi_pins.clk)
        self.comb += ulpi_bus.dir.eq(ulpi_pins.dir)
        self.comb += ulpi_pins.stp.eq(ulpi_bus.stp | stp_ovr)
        dq = TSTriple(8)
        self.specials += dq.get_tristate(ulpi_pins.d)
        self.comb += ulpi_bus.di.eq(dq.i)
        self.comb += dq.o.eq(ulpi_bus.do)
        self.comb += dq.oe.eq(ulpi_bus.doe)
        
        self.submodules.ulpi = RenameClockDomains(
          ULPI(ulpi_bus, ulpi_reg),
          {"sys": "ulpi"}
        )
        
        self.submodules.ucfg = ULPICfg(self.cd_ulpi.clk, cd_rst, ulpi_bus.rst, stp_ovr, ulpi_reg)


        # Receive Path
        self.submodules.ovf_insert = RenameClockDomains(OverflowInserter(),
                {"sys": "ulpi"})

        self.submodules.udata_fifo = RenameClockDomains(al_fifo.AsyncFIFO(ULPI_DATA, 1024),
                {"write":"ulpi", "read":"sys"})


        self.submodules.cfilt = RXCmdFilter()
        self.submodules.cstream = Whacker(1024)
        self.comb += [
                self.ovf_insert.sink.connect(self.ulpi.data_out_source),
                self.udata_fifo.sink.connect(self.ovf_insert.source),
                self.cfilt.sink.connect(self.udata_fifo.source),
                self.cstream.sink.connect(self.cfilt.source)
                ]

        # GPIOs (leds/buttons)
        leds_v = Signal(3)
        self.comb += Cat(led1, led2, led3).eq(~leds_v)

        self.submodules.leds = LED_outputs(leds_v,
                [
                    [self.bist.busy, self.ftdi_bus.tx_ind],
                    [0, self.ftdi_bus.rx_ind],
                    [0]
                ])
        self.submodules.buttons = BTN_status(~btn)
        
        # FTDI Command processor
        self.submodules.randtest = FTDI_randtest()
        self.submodules.cmdproc = CmdProc(self.ftdi_bus, 
                [self.randtest, self.cstream])


        # Bind all device CSRs
        self.csr_map = {
                'leds': 0,
                'buttons' : 1,
                'ucfg' : 2,
                'randtest' : 3,
                'cstream' : 4,
                'sdram_test' : 5,
                }

        self.submodules.csrbankarray = BankArray(self,
            lambda name, _: self.csr_map[name])

        self.submodules.incon = Interconnect(self.cmdproc.master, self.csrbankarray.get_buses())

        # Generate mapfile for tool / sw usage
        r = ""
        for name, csrs, mapaddr, rmap in self.csrbankarray.banks:
            r += "\n# "+name+"\n"
            reg_base = 0x200 * mapaddr
            r += name.upper()+"_BASE = "+hex(reg_base)+"\n"

            for n, csr in enumerate(csrs):
                nr = (csr.size + 7)//8
                r += "%s = %#x\n" % ((name + "_" + csr.name).upper(), reg_base + n)

        # FIXME: build dir should come from command line arg
        open("build/map.txt", "w").write(r)
