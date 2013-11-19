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
from migen.bank.description import AutoCSR, CSRStorage, CSRStatus

import ov3, clocking
from sdram import SDRAMFIFO
from ulpi import ULPI, ULPI_BUS, ULPI_REG, ULPI_DATA
from leds import LED_outputs
from buttons import BTN_status
from whacker.whacker import Whacker
from ovf_insert import OverflowInserter
from cmdproc import CmdProc
from ftdi_bus import FTDI_sync245
from ftdi_lfsr_test import FTDI_randtest
from ulpicfg import ULPICfg
from cfilt import RXCmdFilter

plat = ov3.Platform()

class OV3(Module):
    def __init__(self):
        clk_ref = plat.request("clk50")
        self.submodules.clockgen = clocking.ClockGen(clk_ref)
        self.clock_domains.cd_sys = self.clockgen.cd_sys

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

        self.submodules.sdram = RenameClockDomains(
            SDRAMFIFO(plat.request("sdram"),
                      clk_out=self.clockgen.clk_sdram,
                      clk_sample=self.clockgen.clk_sdram_sample,
                      databits=16, rowbits=13, colbits=9, bankbits=2,
                      inbuf=1024, outbuf=1024, burst=512,
                      tRESET=20000, tCL=3, tRP=4, tRFC=12, tRCD=4,
                      tREFI=780),
            {"read": "sys", "write": "sys"})


        # ULPI
        # TODO - integrate all below into ULPI module
        
        ulpi_bus = Record(ULPI_BUS)
        ulpi_reg = Record(ULPI_REG)

        self.clock_domains.cd_ulpi = ClockDomain()

        cd_rst = Signal()
        self.cd_ulpi.clk = ulpi_bus.clk
        self.cd_ulpi.rst = cd_rst

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

        # cstream to sdram buffer
        self.comb += [
            self.sdram.we.eq(self.cstream.source.stb),
            self.sdram.din.eq(self.cstream.source.payload.raw_bits()),
            self.cstream.source.ack.eq(self.sdram.writable)
            ]

        class DummyStreamSource(Module):
            def __init__(self):
                self.source = Source([("d", 8), ("last", 1)])

        self.submodules.sdram_adaptor = DummyStreamSource()

        self.comb += [
            self.sdram_adaptor.source.stb.eq(self.sdram.readable),
            self.sdram.re.eq(self.sdram_adaptor.source.ack),
            self.sdram_adaptor.source.payload.raw_bits().eq(self.sdram.dout)
            ]

        # GPIOs (leds/buttons)
        leds_v = Signal(3)
        self.comb += Cat(led1, led2, led3).eq(~leds_v)

        self.submodules.leds = LED_outputs(leds_v,
                [
                    [0, self.ftdi_bus.tx_ind],
                    [0, self.ftdi_bus.rx_ind],
                    []
                ])
        self.submodules.buttons = BTN_status(~btn)
        
        # FTDI Command processor
        self.submodules.randtest = FTDI_randtest()
        self.submodules.cmdproc = CmdProc(self.ftdi_bus, 
                [self.randtest, self.sdram_adaptor])


        # Bind all device CSRs
        self.csr_map = {
                'leds': 0,
                'buttons' : 1,
                'ucfg' : 2,
                'randtest' : 3,
                'cstream' : 4,
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


if __name__ == "__main__":
    plat.build_cmdline(OV3())
