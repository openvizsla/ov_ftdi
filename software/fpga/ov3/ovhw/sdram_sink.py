from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState
from migen.genlib.fifo import SyncFIFO
from migen.bank import description, csrgen
from migen.flow.actor import Sink

class SDRAM_Sink(Module, description.AutoCSR):
    def __init__(self, hostif):
        width = flen(hostif.d_write)
        assert width == 16
        
        awidth = flen(hostif.i_addr)
        
        self.sink = Source([('d', 8)])
        
        sdram_fifo = SyncFIFO(width, 32)

        self.submodules.fifo_write_fsm = FSM()
        
        wptr = Signal(awidth)
        
        # FSM to move FIFO data to SDRAM
        
        self.comb += hostif.i_wr.eq(1)
        
        self.fifo_write_fsm.act("IDLE",
            If(sdram_fifo.readable,
                hostif.i_addr.eq(wptr),
                hostif.i_stb.eq(1)
            ),
            If(hostif.i_ack,
                NextState("WRITE")
        )
        
        self.comb += hostif.d_write.eq(sdram_fifo.r)
        
        self.fifo_write_fsm.act("WRITE",
            hostif.d_term.eq(~sdram_fifo.readable),
            sdram_fifo.re.eq(hostif.d_stb),
            If(~sdram_fifo.readable & ~hostif.d_stb,
                NextState("WAIT")
            ).Elif(~sdram_fifo.readable & hostif.d_stb,
                NextState("IDLE")
            )
        )
        
        self.fifo_write_fsm.act("WAIT",
            hostif.d_term.eq(1),
            If(hostif.d_stb,
                NextState("IDLE")
            )
        )
        
        self.sync += If(hostif.d_stb &~ hostif.d_term,
            self.wptr.eq(self.wptr + 1))

        self.comb += [
            sdram_fifo.w.eq(self.sink.payload.d),
            sdram_fifo.we.eq(self.sink.stb),
            self.sink.ack.eq(sdram_fifo.writable)
        ]
            
