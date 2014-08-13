from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState
from migen.genlib.fifo import SyncFIFO
from migen.bank import description, csrgen
from migen.flow.actor import Source

from ovhw.whacker.util import Acc, Acc_inc

Output = Signal
Input = Signal

class SDRAM_Host_Read(Module, description.AutoCSR):
    def __init__(self, hostif):
        width = flen(hostif.d_write)
        assert width == 16
        
        awidth = flen(hostif.i_addr)
        
        self.source = Source([('d', 8), ('last', 1)])
        
        go = Signal()
        gor = Signal()
        rptr = Signal(awidth)
        self.rptr = rptr
        rptr_w = Signal(awidth)
        rptr_we = Signal()
        self.wptr = Signal(awidth)
        
        # CSRs
        
        ##
        
        self._debug_i_stb = description.CSRStatus(32)
        self._debug_i_ack = description.CSRStatus(32)
        self._debug_d_stb = description.CSRStatus(32)
        self._debug_d_term = description.CSRStatus(32)
        self._debug_s0 = description.CSRStatus(32)
        self._debug_s1 = description.CSRStatus(32)
        self._debug_s2 = description.CSRStatus(32)
        
        self.submodules.i_stb_acc = Acc_inc(32)
        self.submodules.i_ack_acc = Acc_inc(32)
        self.submodules.d_stb_acc = Acc_inc(32)
        self.submodules.d_term_acc = Acc_inc(32)
        
        self.comb += self._debug_i_stb.status.eq(self.i_stb_acc.v)
        self.comb += self._debug_i_ack.status.eq(self.i_ack_acc.v)
        self.comb += self._debug_d_stb.status.eq(self.d_stb_acc.v)
        self.comb += self._debug_d_term.status.eq(self.d_term_acc.v)
        self.comb += If(hostif.i_stb, self.i_stb_acc.inc())
        self.comb += If(hostif.i_ack, self.i_ack_acc.inc())
        self.comb += If(hostif.d_stb, self.d_stb_acc.inc())
        self.comb += If(hostif.d_term, self.d_term_acc.inc())
        
        self.submodules.s0_acc = Acc_inc(32)
        self.submodules.s1_acc = Acc_inc(32)
        self.submodules.s2_acc = Acc_inc(32)

        self.comb += self._debug_s0.status.eq(self.s0_acc.v)
        self.comb += self._debug_s1.status.eq(self.s1_acc.v)
        self.comb += self._debug_s2.status.eq(self.s2_acc.v)
        
        ##
        
        self._ring_base = description.CSRStorage(awidth)
        self._ring_end = description.CSRStorage(awidth)
        
        # rptr readback
        self._rptr_status = description.CSRStatus(awidth)
        self.comb += self._rptr_status.status.eq(rptr)
        
        # 'go' bit
        
        self._go = description.CSRStorage(1)
        
        self.comb += go.eq(self._go.storage[0])
        self.sync += gor.eq(go)
        
        # state machine to read

        self.submodules.sdram_read_fsm = FSM()
        
        host_burst_length = 16
        sdram_fifo = SyncFIFO(width, host_burst_length)
        self.submodules += sdram_fifo

        # we always read (never write)
        self.comb += hostif.i_wr.eq(0)

        # blocked
        
        blocked = Signal()
        self.comb += blocked.eq(rptr == self.wptr)
        
        # wait until there's data and go, and then when the fifo has space, issue request.
        
        self.sdram_read_fsm.act("BLOCKED",
            self.s2_acc.inc(),
            If(go & ~blocked, NextState("IDLE"))
        )
        
        self.sdram_read_fsm.act("IDLE",
            self.s0_acc.inc(),
            hostif.i_addr.eq(rptr),
            hostif.i_stb.eq(sdram_fifo.writable),
            If (hostif.i_stb & hostif.i_ack,
                NextState("DATA")
            )
        )

        # read until fifo is full; when fifo is not writable but data was received,
        # abort SDRAM read request.

        wrap = Signal()
        self.comb += wrap.eq(self.rptr == self._ring_end.storage)
        
        self.sdram_read_fsm.act("DATA",
            self.s1_acc.inc(),
            hostif.d_term.eq(~sdram_fifo.writable | ~go | blocked | wrap),
            If (hostif.d_term,
                If (hostif.d_stb,
                    NextState("BLOCKED")
                ).Else(
                    NextState("WAIT")
                )
            )
        )
        
        self.sdram_read_fsm.act("WAIT",
            hostif.d_term.eq(1),
            If (hostif.d_stb,
                NextState("BLOCKED")
            )
        )

        # allow rptr to be updated via CSR. Otherwise,
        # increment read point whenever valid data is fed into the fifo.

        rptr_next = Signal(awidth)
        self.comb += If(wrap, rptr_next.eq(self._ring_base.storage)).Else(rptr_next.eq(self.rptr + 1))
        
        self.sync += \
            If(go &~ gor, 
                rptr.eq(self._ring_base.storage),
            ).Elif(hostif.d_stb &~hostif.d_term | wrap, 
                rptr.eq(rptr_next))

        self.comb += sdram_fifo.we.eq(hostif.d_stb &~ hostif.d_term)
        self.comb += sdram_fifo.din.eq(hostif.d_read)
        
        # fifo to host interface
        
        self.submodules.host_write_fsm = FSM()
        
        burst_rem = Signal(max = host_burst_length) 
        burst_rem_next = Signal(max = host_burst_length)
        
        self.comb += burst_rem_next.eq(burst_rem)
        self.sync += burst_rem.eq(burst_rem_next)

        # when the sdram_fifo is not anymore writable, start bursting out that data.
        
        self.host_write_fsm.act("IDLE",
            self.source.payload.d.eq(0xD0),
            self.source.stb.eq(sdram_fifo.readable &~ sdram_fifo.writable),
            If(self.source.ack & self.source.stb,
                burst_rem_next.eq(host_burst_length - 1),
                NextState("SEND_DATA_ODD")
            )
        )
        
        # when byte available, write low byte until ack'ed.
        
        self.host_write_fsm.act("SEND_DATA_ODD",
            self.source.payload.d.eq(sdram_fifo.dout[0:8]),
            self.source.stb.eq(sdram_fifo.readable),
            If (self.source.stb & self.source.ack,
                NextState("SEND_DATA_EVEN")
            )
        )
        
        # write high byte. when ack'ed, read next byte, unless we hit the burst length limit.
        
        self.host_write_fsm.act("SEND_DATA_EVEN",
            self.source.payload.d.eq(sdram_fifo.dout[8:16]),
            self.source.payload.last.eq(burst_rem == 0),
            self.source.stb.eq(1),
            sdram_fifo.re.eq(self.source.ack),
            If (self.source.ack, 
                If (burst_rem != 0,
                    NextState("SEND_DATA_ODD"),
                    burst_rem_next.eq(burst_rem - 1)
                ).Else(
                    NextState("IDLE")
                )
            )
        )
