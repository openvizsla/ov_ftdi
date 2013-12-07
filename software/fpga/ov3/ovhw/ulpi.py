from migen.fhdl.std import *
from migen.fhdl import verilog
from migen.sim.generic import Simulator, TopLevel
from migen.genlib.fsm import FSM, NextState
from migen.genlib.record import *
from migen.flow.actor import Source

from ovhw.constants import *

ULPI_BUS = [
	("rst", 1, DIR_M_TO_S),
	("nxt", 1, DIR_S_TO_M),
	("dir", 1, DIR_S_TO_M),
	("stp", 1, DIR_M_TO_S),
	("do", 8, DIR_M_TO_S),
	("di", 8, DIR_S_TO_M),
	("doe", 1, DIR_M_TO_S)
]

ULPI_REG = [
	("waddr", 6, DIR_M_TO_S),
	("raddr", 6, DIR_M_TO_S),
	("wdata", 8, DIR_M_TO_S),
	("rdata", 8, DIR_S_TO_M),
	("wreq", 1, DIR_M_TO_S),
	("wack", 1, DIR_S_TO_M),
	("rreq", 1, DIR_M_TO_S),
	("rack", 1, DIR_S_TO_M)
]

ULPI_DATA = [
	("d", 8, DIR_M_TO_S),
	("rxcmd", 1, DIR_M_TO_S),
]

class ULPI_pl(Module):
    """
    ULPI Physical layer interface. Connects internal unidirectional busses to
    bidirectional ULPI interface. Instantiated as as separate module to allow
    simulation testing of unidirectional controller
    """
    def __init__(self, ulpi_pins, ulpi_cd_rst=0, stp_ovr=0):
        self.clock_domains.cd_ulpi = ClockDomain()
        self.cd_ulpi.clk = ulpi_pins.clk
        self.cd_ulpi.rst = ulpi_cd_rst

        self.ulpi_bus = ulpi_bus = Record(ULPI_BUS)

        # CTRL->PHY
        self.comb += ulpi_pins.rst.eq(~ulpi_bus.rst)
        self.comb += ulpi_pins.stp.eq(ulpi_bus.stp | stp_ovr)

        # PHY->CTRL
        self.comb += ulpi_bus.nxt.eq(ulpi_pins.nxt)
        self.comb += ulpi_bus.dir.eq(ulpi_pins.dir)

        # BIDIR
        dq = TSTriple(8)
        self.specials += dq.get_tristate(ulpi_pins.d)
        self.comb += ulpi_bus.di.eq(dq.i)
        self.comb += dq.o.eq(ulpi_bus.do)
        self.comb += dq.oe.eq(ulpi_bus.doe)


class ULPI_ctrl(Module):
	def __init__(self, ulpi_bus, ulpi_reg):

		ulpi_data_out = Signal(8)
		ulpi_data_tristate = Signal()
		
		ulpi_data_next = Signal(8)
		ulpi_data_tristate_next = Signal()
		ulpi_stp_next = Signal()

		ulpi_state_rx = Signal()
		ulpi_state_rrd = Signal()
		
		self.data_out_source = Source(ULPI_DATA)

		RegWriteReqR = Signal()
		RegReadReqR = Signal()
		RegWriteReq = Signal()
		RegReadReq = Signal()
		RegReadAckSet = Signal()
		RegWriteAckSet = Signal()

		# register the reg read/write requests
		self.sync += RegReadReqR.eq(ulpi_reg.rreq)
		self.sync += RegWriteReqR.eq(ulpi_reg.wreq)
		
		# signal when read/write is requested but not done
		self.comb += RegReadReq.eq(RegReadReqR & ~ulpi_reg.rack)
		v = (RegReadReqR & ~ulpi_reg.rack)
		self.comb += RegWriteReq.eq(RegWriteReqR & ~ulpi_reg.wack)
		
		# ack logic: set ack=0 when req=0, set ack=1 when access done
		self.sync += If(~RegReadReqR, ulpi_reg.rack.eq(0)
			).Elif(RegReadAckSet, ulpi_reg.rack.eq(1))
		self.sync += If(~RegWriteReqR, ulpi_reg.wack.eq(0)
			).Elif(RegWriteAckSet, ulpi_reg.wack.eq(1))
			
		exp = If(~RegWriteReqR, ulpi_reg.wack.eq(0)).Elif(RegWriteAckSet, ulpi_reg.wack.eq(1))

		# output data if required by state
		self.comb += ulpi_bus.stp.eq(ulpi_stp_next)
		self.comb += ulpi_data_out.eq(ulpi_data_next)
		self.comb += ulpi_data_tristate.eq(ulpi_data_tristate_next)
		self.comb += ulpi_bus.do.eq(ulpi_data_out)
		self.comb += ulpi_bus.doe.eq(~ulpi_data_tristate)
		


		# capture RX data at the end of RX, but only if no turnaround was requested
		# We also support "stuffing" data, to indicate conditions such as:
		#  - Simultaneous DIR + NXT assertion
		#	(the spec doesn't require an RXCMD - DIR+NXT asserting may be the'
		#	only SOP signal)
		#  - End-of-packet 
		#	(Packets may end without an RXCMD, unless an error occurs)
		ulpi_rx_stuff   = Signal()
		ulpi_rx_stuff_d = Signal(8)

		self.sync += self.data_out_source.stb.eq(1)
		self.sync += If(ulpi_rx_stuff, 
						self.data_out_source.payload.d.eq(ulpi_rx_stuff_d),
						self.data_out_source.payload.rxcmd.eq(1)
					 ).Elif(ulpi_state_rx & ulpi_bus.dir,
						If(~ulpi_bus.nxt,
							self.data_out_source.payload.d.eq(ulpi_bus.di & RXCMD_MASK),
							self.data_out_source.payload.rxcmd.eq(1)
						).Else(
							self.data_out_source.payload.d.eq(ulpi_bus.di),
							self.data_out_source.payload.rxcmd.eq(0)
						)
					 ).Else(
                        self.data_out_source.payload.d.eq(RXCMD_MAGIC_NOP),
                        self.data_out_source.payload.rxcmd.eq(1)
                    )

		# capture register reads at the end of RRD
		self.sync += If(ulpi_state_rrd,ulpi_reg.rdata.eq(ulpi_bus.di))

		fsm = FSM()
		self.submodules += fsm
		
		fsm.act("IDLE", 
			ulpi_data_next.eq(0x00), # NOOP
			ulpi_data_tristate_next.eq(0),
			ulpi_stp_next.eq(0),
			If(~ulpi_bus.dir & ~ulpi_bus.nxt & ~(RegWriteReq | RegReadReq), 
				NextState("IDLE")
			).Elif(ulpi_bus.dir, # TA, and then either RXCMD or Data
				NextState("RX"),
				ulpi_data_tristate_next.eq(1),
				# If dir & nxt, we're starting a packet, so stuff a custom SOP
				If(ulpi_bus.nxt,
					ulpi_rx_stuff.eq(1),
					ulpi_rx_stuff_d.eq(RXCMD_MAGIC_SOP)
				)
			).Elif(RegWriteReq,
				NextState("RW0"),
				ulpi_data_next.eq(0x80 | ulpi_reg.waddr), # REGW
				ulpi_data_tristate_next.eq(0),
				ulpi_stp_next.eq(0)
			).Elif(RegReadReq,
				NextState("RR0"),
				ulpi_data_next.eq(0xC0 | ulpi_reg.raddr), # REGR
				ulpi_data_tristate_next.eq(0),
				ulpi_stp_next.eq(0)
			).Else(
				NextState("ERROR")
			))

		fsm.act("RX", 
			If(ulpi_bus.dir, # stay in RX
				NextState("RX"),
				ulpi_state_rx.eq(1),
				ulpi_data_tristate_next.eq(1)
			).Else( # TA back to idle
				# Stuff an EOP on return to idle
				ulpi_rx_stuff.eq(1),
				ulpi_rx_stuff_d.eq(RXCMD_MAGIC_EOP),
				ulpi_data_tristate_next.eq(0), 
				NextState("IDLE")
			))
	
		fsm.act("RW0", 
			If(ulpi_bus.dir,
				NextState("RX"),
				ulpi_data_tristate_next.eq(1),
			).Elif(~ulpi_bus.dir,
				ulpi_data_next.eq(0x80 | ulpi_reg.waddr), # REGW
				ulpi_data_tristate_next.eq(0),
				ulpi_stp_next.eq(0),
				If(ulpi_bus.nxt, NextState("RWD")).Else(NextState("RW0")),
			).Else(
				NextState("ERROR")
			))
		
		fsm.act("RWD",
			If(ulpi_bus.dir,
				NextState("RX"),
				ulpi_data_tristate_next.eq(1)
			).Elif(~ulpi_bus.dir & ulpi_bus.nxt,
				NextState("RWS"),
				ulpi_data_next.eq(ulpi_reg.wdata),
				ulpi_data_tristate_next.eq(0),
				ulpi_stp_next.eq(0)
			).Else(
				NextState("ERROR")
			),
			)
		
		fsm.act("RWS",
			If(~ulpi_bus.dir,
				NextState("IDLE"),
				ulpi_data_next.eq(0x00), # NOOP
				ulpi_data_tristate_next.eq(0),
				ulpi_stp_next.eq(1),
				RegWriteAckSet.eq(1)
			).Elif(ulpi_bus.dir,
				NextState("RX"),
				ulpi_data_tristate_next.eq(1),
			),
			)
		
		fsm.act("RR0",
			If(~ulpi_bus.dir,
				ulpi_data_next.eq(0xC0 | ulpi_reg.raddr), # REGR
				NextState("RR1")
			).Elif(ulpi_bus.dir,
				NextState("RX"),
				RegWriteAckSet.eq(1)
			).Else(
				NextState("ERROR")
			))
		
		fsm.act("RR1",
			If(~ulpi_bus.dir & ulpi_bus.nxt, # PHY accepts REGR
				ulpi_data_tristate_next.eq(1), # TA
				NextState("RR2")
			).Elif(~ulpi_bus.dir & ~ulpi_bus.nxt, # PHY delays REGR
				ulpi_data_next.eq(0xC0 | ulpi_reg.raddr), # REGR
				NextState("RR1")
			).Elif(ulpi_bus.dir,
				NextState("RX"),
				RegWriteAckSet.eq(1)
			).Else(
				NextState("ERROR")
			))
		
		fsm.act("RR2",
			ulpi_data_tristate_next.eq(1),
			If(~ulpi_bus.nxt, # REGR continue
				NextState("RRD")
			).Elif(ulpi_bus.dir, # PHY indicates RX
				NextState("RX"),
				RegWriteAckSet.eq(1)
			).Else(
				NextState("ERROR")
			))
		
		fsm.act("RRD",
			If(ulpi_bus.dir & ~ulpi_bus.nxt,
				NextState("IDLE"),
				RegReadAckSet.eq(1),
				ulpi_state_rrd.eq(1),
			).Elif(ulpi_bus.dir & ulpi_bus.nxt,
				NextState("RX"),
				RegWriteAckSet.eq(1)
			).Else(
				NextState("ERROR")
			),
				ulpi_data_tristate_next.eq(1),
			)

		fsm.act("ERROR", NextState("IDLE"))



class FakeULPI(Module):
	def __init__(self, ulpi_bus):
		self.ulpi_bus = ulpi_bus
		
		fsm = FSM()
		self.submodules += fsm
		
		self.WantRx = Signal()
		self.RxByte = Signal(8)
		self.RxCmd = Signal()
		self.NextCycleRx = Signal()
		
		self.RegWriteValid = Signal()
		self.RegAddrW = Signal(6)
		self.RegDataW = Signal(8)

		self.RegRead = Signal()
		self.RegAddrR = Signal(6)
		self.RegDataR = Signal(8)
		
		self.StateTX = Signal()
		
		SetRegAddrR = Signal()
		SetRegAddrW = Signal()
		SetRegDataW = Signal()
		
		fsm.act("TXCMD", 
			If(self.WantRx, NextState("TA1")
			).Elif(ulpi_bus.do[6:8] == 0b10, NextState("RW0") # REGW
			).Elif(ulpi_bus.do[6:8] == 0b11, NextState("RR0") # REGR
			).Else(NextState("TXCMD"), 
				ulpi_bus.dir.eq(0),
				self.StateTX.eq(1)
			))
		
		fsm.act("TA1", 
			NextState("RX"), 
			ulpi_bus.dir.eq(1),
			self.NextCycleRx.eq(1)
			)
		
		fsm.act("RX",
			If(self.WantRx, NextState("RX"),
				ulpi_bus.dir.eq(1),
				ulpi_bus.di.eq(self.RxByte),
				ulpi_bus.nxt.eq(self.RxCmd),
				self.NextCycleRx.eq(1)
			).Else(NextState("TA2")
			))
		
		fsm.act("TA2", 
				NextState("TXCMD"),
				ulpi_bus.dir.eq(0)
			)
		
		fsm.act("RW0", 
			If(self.WantRx, NextState("TA1")
			).Else(
				NextState("RW1"),
				ulpi_bus.dir.eq(0),
				ulpi_bus.nxt.eq(1),
				SetRegAddrW.eq(1)
			))
		
		fsm.act("RW1",
			NextState("RW2"),
			ulpi_bus.dir.eq(0),
			ulpi_bus.nxt.eq(1),
			SetRegDataW.eq(1)
			)
		
		fsm.act("RW2",
			NextState("TXCMD"),
			self.RegWriteValid.eq(ulpi_bus.stp))
		
		fsm.act("RR0",
			If(self.WantRx, NextState("TA1")
			).Else(
				NextState("RR1"),
				SetRegAddrR.eq(1),
				ulpi_bus.nxt.eq(1),
			))
		
		fsm.act("RR1", 
			ulpi_bus.dir.eq(1),
			If(self.WantRx, 
				NextState("RX"), 
				ulpi_bus.nxt.eq(1), # indicating abort
			).Else(
				NextState("RRD")
			))
		
		fsm.act("RRD",
			ulpi_bus.dir.eq(1),
			ulpi_bus.di.eq(self.RegDataR),
			NextState("TA2"
		))

		self.sync += If(SetRegAddrR, self.RegAddrR.eq(ulpi_bus.do[0:6]))
		self.sync += self.RegRead.eq(SetRegAddrR)

		self.sync += If(SetRegAddrW, self.RegAddrW.eq(ulpi_bus.do[0:6]))
		self.sync += If(SetRegDataW, self.RegDataW.eq(ulpi_bus.do))
		
	def do_simulation(self, s):
		if s.cycle_counter == -1:
			self.Regs = {
				0x00: 0x24,
				0x01: 0x04,
				0x02: 0x09,
				0x03: 0x00,
				0x04: 0x41,
				0x07: 0x00,
				0x0A: 0x06,
				0x0D: 0x1F,
				0x10: 0x1F,
			}
			
			self.packets = [
				[17, 0, bytes.fromhex("DEADBEEF")],
				[100, 0, bytes.fromhex("FEEDBABE")]
			]
			
			for i in range(128):
				self.packets.append([200 + i * 16, 1, b"3"])

			for i in range(128):
				self.packets.append([200 + i * (16+7), 0, b"ABCD"])
			
			self.packets.sort(key=lambda x: x[0])
			
			self.CurrentRx = None

			return

		if self.CurrentRx is None and len(self.packets) and s.cycle_counter >= self.packets[0][0]:
			self.CurrentRx = self.packets.pop(0)

		s.wr(self.WantRx, self.CurrentRx is not None)
	
		if self.CurrentRx is not None and s.rd(self.NextCycleRx):
			s.wr(self.RxByte, int(self.CurrentRx[2][0]))
			s.wr(self.RxCmd, self.CurrentRx[1])
			self.CurrentRx[2] = self.CurrentRx[2][1:]
			if not len(self.CurrentRx[2]):
				self.CurrentRx = None
			
		if s.rd(self.RegWriteValid):
			Addr = s.rd(self.RegAddrW)
			Data = s.rd(self.RegDataW)
			print("%06d FakeULPI REGW %02x = [%02x]" % (s.cycle_counter, Addr, Data))
			
			if Addr in [0x05,0x08,0x0B,0x0E,0x11,0x17,0x1A,0x1E]:
				self.Regs[Addr] |= Data
			elif Addr in [0x06, 0x09, 0x0C, 0x0F, 0x12, 0x18, 0x1B, 0x1F]:
				self.Regs[Addr] &= ~Data
			else: 
				self.Regs[Addr] = Data

		if s.rd(self.RegRead):
			Data = self.Regs.get(s.rd(self.RegAddrR), 0)
			s.wr(self.RegDataR, Data)
			print("%06d FakeULPI REGR %02x = [%02x]" % (s.cycle_counter, s.rd(self.RegAddrR), Data))
	
	do_simulation.initialize = True

class ULPIRegTest(Module):
	def __init__(self, ulpi_reg):
		
		ReadAddress = Signal(6)
		
		write_fsm = FSM()
		self.submodules += write_fsm
		
		def delay_clocks(v, d):
			for i in range(d):
				n = Signal()
				self.sync += n.eq(v)
				v = n
			return v
		
		ulpi_reg_wack = delay_clocks(ulpi_reg.wack, 2)
		ulpi_reg_rack = delay_clocks(ulpi_reg.rack, 2)
		
		write_fsm.delayed_enter("RESET", "WRITE_HS_SNOOP", 16)

		write_fsm.act("WRITE_HS_SNOOP",
			ulpi_reg.waddr.eq(0x4),
			ulpi_reg.wdata.eq(0x48),
			ulpi_reg.wreq.eq(1),
			If(ulpi_reg_wack, NextState("WRITE_IDLE")))
		
		write_fsm.act("WRITE_IDLE",
			ulpi_reg.wreq.eq(0))
		
		read_fsm = FSM()
		self.submodules += read_fsm

		read_fsm.delayed_enter("RESET", "READ_REG", 16)
		
		read_fsm.act("READ_REG",
			ulpi_reg.raddr.eq(ReadAddress),
			ulpi_reg.rreq.eq(1),
			If(ulpi_reg_rack, NextState("READ_ACK")))
		
		self.sync += If(ulpi_reg_rack & ulpi_reg.rreq, ReadAddress.eq(ReadAddress + 1))
		
		read_fsm.act("READ_ACK",
			ulpi_reg.rreq.eq(0),
			If(~ulpi_reg_rack, NextState("READ_WAIT")))
		
		read_fsm.delayed_enter("READ_WAIT", "READ_REG", 16)

class TestULPI(Module):
	def __init__(self, clock, use_regtest):

		self.use_regtest = use_regtest

		ulpi_reg = Record(ULPI_REG)
		
		Counter = Signal(8)
		self.sync += Counter.eq(Counter + 1)
		
		self.clock_domains.cd_ulpi = ClockDomain()

		ulpi_bus_master = Record(ULPI_BUS)
		ulpi_bus_slave = Record(ULPI_BUS)
		
		self.comb += ulpi_bus_master.connect(ulpi_bus_slave)

		self.submodules.ulpi = RenameClockDomains(
			ULPI(ulpi_bus_master, ulpi_reg),
			{"sys": "ulpi"}
		)
		
		self.submodules.fakeulpi = RenameClockDomains(
			FakeULPI(ulpi_bus_slave),
			{"sys": "ulpi"}
		)
		
		if use_regtest:
			self.submodules.regtest = RenameClockDomains(
				ULPIRegTest(ulpi_reg), {"sys":"ulpi"}
			)
			ulpi_reg_master = Record(ULPI_REG)
			self.comb += ulpi_reg_master.connect(ulpi_reg)
		
		self.cd_ulpi.clk = ulpi_bus_master.clk
		self.cd_ulpi.rst = ulpi_bus_master.rst
		
		self.comb += ulpi_bus_slave.clk.eq(clock.clk)
		self.comb += ulpi_bus_master.rst.eq(clock.rst)
		
		self.ulpi_reg = ulpi_reg

	def do_simulation(self, s):
	
		if s.cycle_counter == -1:
			self.tw = [
				(32, 0x4, 0x48),
			]

			self.tr = [
				(16, 0),
			]
			
			for i in range(20):
				self.tr.append((i * 16 + i, i))
			
			return
		
		if not self.regtest:
			if len(self.tr) > 0 and ~s.rd(self.ulpi_reg.rack) & ~s.rd(self.ulpi_reg.rreq) & s.cycle_counter >= self.tr[0][0]:
				t = self.tr.pop(0)
				s.wr(self.ulpi_reg.raddr, t[1])
				s.wr(self.ulpi_reg.rreq, 1)
			
			if len(self.tw) > 0 and ~s.rd(self.ulpi_reg.wack) & ~s.rd(self.ulpi_reg.wreq) & s.cycle_counter >= self.tw[0][0]:
				t = self.tw.pop(0)
				s.wr(self.ulpi_reg.waddr, t[1])
				s.wr(self.ulpi_reg.wreq, 1)
				s.wr(self.ulpi_reg.wdata, t[2])

		if s.rd(self.ulpi_reg.rack) & s.rd(self.ulpi_reg.rreq):
			print("%06d TestULPI REGR [%02x] = %02x" % (s.cycle_counter, s.rd(self.ulpi_reg.raddr), s.rd(self.ulpi_reg.rdata)))
			s.wr(self.ulpi_reg.rreq, 0)

		if s.rd(self.ulpi_reg.wack) & s.rd(self.ulpi_reg.wreq):
			print("%06d TestULPI REGW [%02x] = %02x" % (s.cycle_counter, s.rd(self.ulpi_reg.waddr), s.rd(self.ulpi_reg.wdata)))
			s.wr(self.ulpi_reg.wreq, 0)

		if s.rd(self.ulpi.data_out_source.stb):
			print("%06d TestULPI [%02x] RXCMD=%d" % (s.cycle_counter, s.rd(self.ulpi.data_out_source.payload.d), s.rd(self.ulpi.data_out_source.payload.rxcmd)))

	do_simulation.initialize = True

if __name__ == "__main__":
	from migen.sim.generic import Simulator, TopLevel
	tl = TopLevel("ulpi.vcd")
	test = TestULPI(tl.clock_domains[0], True)
	sim = Simulator(test, tl)
	sim.run(5000)
	#print(verilog.convert(test, set(ulpi_data.flatten()) | set(ulpi_reg.flatten()) ))
