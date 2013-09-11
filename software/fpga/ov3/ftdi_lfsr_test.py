# Module for generating a pseudorandom bitstream for testing data backhaul from FTDI chip
# Packets are of form 0xAA n* rand


from migen.genlib.cdc import MultiReg
from migen.bank import description, csrgen
from migen.bus.csr import Initiator, Interconnect
from migen.bus.transactions import *
from migen.genlib.fsm import FSM, NextState
from migen.flow.actor import Source

class FTDI_randtest(Module, description.AutoCSR):
    def __init__(self):
        self._size = description.CSRStorage(8, reset=8)
        self._cfg = description.CSRStorage(1, reset=0)

        self.source = Source([('d', 8), ('last', 1)])

        START_BYTE = 0xAA

        self.lfsr_state = Signal(17)
        self.lfsr_state_next = Signal(17)


        self.sync += If(~self._cfg.storage[0],
                self.lfsr_state.eq(1)
            ).Else(
                self.lfsr_state.eq(self.lfsr_state_next)
                )
        
        self.bytecount = Signal(8)
        self.bytecount_next = Signal(8)
        self.comb += [
                self.lfsr_state_next.eq(self.lfsr_state),
                self.bytecount_next.eq(self.bytecount),
                self.source.payload.last.eq(0)
            ]
        self.sync += self.bytecount.eq(self.bytecount_next)

        self.submodules.fsm = FSM()

        self.fsm.act("IDLE", 
                If(self._cfg.storage[0], NextState("SEND_HEAD")))

        self.fsm.act("SEND_HEAD", 
                self.source.payload.d.eq(0xAA),
                self.source.stb.eq(1),
                If(self.source.ack,
                    NextState("SEND_SIZE")))

        self.fsm.act("SEND_SIZE",
                self.source.payload.d.eq(self._size.storage),
                self.source.stb.eq(1),
                If(self.source.ack,
                    self.bytecount_next.eq(0),
                    NextState("SEND_DATA")
                ),
            )

        self.fsm.act("SEND_DATA",
                self.source.payload.d.eq(self.lfsr_state),
                self.source.stb.eq(1),
                If(self.bytecount + 1 == self._size.storage,
                    self.source.payload.last.eq(1)),

                If(self.source.ack,
                    self.lfsr_state_next.eq(
                        Cat(
                            self.lfsr_state[16] ^ 
                            self.lfsr_state[14] ^ 
                            self.lfsr_state[13] ^ 
                            self.lfsr_state[11], self.lfsr_state)
                        ),
                    self.bytecount_next.eq(self.bytecount + 1),

                    If(self.bytecount + 1 == self._size.storage,
                        NextState("IDLE"))
                    )
                )


class TestRandom(Module):
    def __init__(self, clock):
        from cmdproc import CmdProc

        self.submodules.tr = FTDI_randtest()

        class ff:
            def __getattr__(self, attrname):
                if not attrname in self.__dict__:
                    self.__dict__[attrname] = ff()

                return self.__dict__[attrname]


        self.ff = ff()

        self.ff.incoming_fifo.re = Signal()
        self.ff.incoming_fifo.readable = Signal(reset=0)
        self.ff.incoming_fifo.dout = Signal(8)

        #self.sync += self.ff.incoming_fifo.readable.eq(0)
        #self.sync += self.ff.incoming_fifo.dout.eq(0)

        self.ff.output_fifo.we = Signal()
        self.ff.output_fifo.writable = Signal(reset=1)
        self.ff.output_fifo.din = Signal(8)

        self.submodules.cm = CmdProc(self.ff, self.tr)

        #self.tr.source.ack.reset = 1

    def do_simulation(self, s):
        if s.cycle_counter in range(3,8):
            print ("set %d" % s.cycle_counter)
            s.wr(self.ff.incoming_fifo.readable, 1)

            s.wr(self.ff.incoming_fifo.dout,
                    [0x55, 0x0, 0x0, 0x0, 0x0][s.cycle_counter - 3])
            #s.wr(self.tr._cfg.storage, 0)

        
if __name__ == "__main__":
    from migen.sim.generic import Simulator, TopLevel

    tl = TopLevel("sdram.vcd")

    test = TestRandom(tl.clock_domains[0])
    sim = Simulator(test, tl)
    sim.run(500)
