from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState
from migen.genlib.fifo import SyncFIFO
from migen.bank import description, csrgen
from migen.flow.actor import Sink

from ovhw.whacker.util import Acc, Acc_inc

class SDRAM_Sink(Module, description.AutoCSR):
    def __init__(self, hostif, max_burst_length = 256):
        width = flen(hostif.d_write)
        assert width == 16

        awidth = flen(hostif.i_addr)

        self.sink = Sink([('d', 8), ('last', 1)])

        self.submodules.sdram_fifo = SyncFIFO(width, max_burst_length)

        self.submodules.fifo_write_fsm = FSM()

        self.wptr = Signal(awidth)

        # CSRs

        self._wptr = description.CSRStatus(awidth)
        self.comb += self._wptr.status.eq(self.wptr)

        self._ring_base = description.CSRStorage(awidth)
        self._ring_end = description.CSRStorage(awidth)
        self._go = description.CSRStorage(1)

        go = self._go.storage[0]

        self.submodules.wrap_count_acc = Acc_inc(32)
        self.wrap_count = description.CSRStatus(32)
        self.comb += self.wrap_count.status.eq(self.wrap_count_acc.v)

        # wptr wrap around

        wrap = Signal()
        self.comb += wrap.eq(self.wptr == self._ring_end.storage)
        wptr_next = Signal(awidth)
        self.comb += If(wrap, wptr_next.eq(self._ring_base.storage)).Else(wptr_next.eq(self.wptr + 1))

        # debug

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

        # FSM to move FIFO data to SDRAM

        burst_rem = Signal(max = max_burst_length)
        burst_rem_next = Signal(max = max_burst_length)

        self.comb += burst_rem_next.eq(burst_rem)
        self.sync += burst_rem.eq(burst_rem_next)

        self.comb += hostif.i_wr.eq(1)

        blocked = Signal()

        rptr = Signal(awidth)
        self.rptr = rptr

        self.comb += blocked.eq(rptr == wptr_next)

        # start writing data if
        # - 'go'-signal set, and
        # - input data available
        # - not blocked

        self.fifo_write_fsm.act("IDLE",
            self.s0_acc.inc(),
            If(self.sdram_fifo.readable & go & ~blocked,
                hostif.i_addr.eq(self.wptr),
                hostif.i_stb.eq(1),
                burst_rem_next.eq(max_burst_length - 1)
            ),
            If(hostif.i_ack,
                NextState("WRITE")
            )
        )

        self.comb += hostif.d_write.eq(self.sdram_fifo.dout)

        # stop writing if 
        # - max burst length reached, or
        # - no more input data, or
        # - wrap
        # - blocked

        self.fifo_write_fsm.act("WRITE",
            self.s1_acc.inc(),
            hostif.d_term.eq((burst_rem == 0) | ~self.sdram_fifo.readable | wrap | blocked),
            self.sdram_fifo.re.eq(hostif.d_stb &~ hostif.d_term),
            If(~hostif.d_term & hostif.d_stb,
                burst_rem_next.eq(burst_rem_next - 1)
            ),
            If(hostif.d_term & ~hostif.d_stb,
                NextState("WAIT")
            ).Elif(hostif.d_term & hostif.d_stb,
                NextState("IDLE")
            )
        )

        self.fifo_write_fsm.act("WAIT",
            self.s2_acc.inc(),
            hostif.d_term.eq(1),
            If(hostif.d_stb,
                NextState("IDLE")
            )
        )


        # 'go'-signal edge detect
        gor = Signal()
        self.sync += gor.eq(go)

        # wrap around counter
        self.comb += If(wrap & hostif.d_stb &~ hostif.d_term, self.wrap_count_acc.inc())

        # update wptr
        self.sync += If(go &~ gor,
                self.wptr.eq(self._ring_base.storage),
            ).Elif((hostif.d_stb &~ hostif.d_term) | wrap,
                self.wptr.eq(wptr_next)
            )

        # sink into fifo

        self.submodules.fifo_fsm = FSM()

        capture_low = Signal()
        din_low = Signal(8)

        self.comb += self.sdram_fifo.din.eq(Cat(din_low, self.sink.payload.d))

        self.sync += If(capture_low, din_low.eq(self.sink.payload.d))

        self.fifo_fsm.act("READ_LOW",
            capture_low.eq(1),
            self.sink.ack.eq(1),
            If(self.sink.stb,
                NextState("READ_HI")
            )
        )

        self.fifo_fsm.act("READ_HI",
            self.sdram_fifo.we.eq(self.sink.stb),
            self.sink.ack.eq(self.sdram_fifo.writable),
            If(self.sink.ack & self.sink.stb,
                NextState("READ_LOW")
            )
        )
