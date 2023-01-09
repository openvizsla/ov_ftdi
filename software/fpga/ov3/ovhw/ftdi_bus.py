from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.fsm import *
from migen.genlib.fifo import *

class FTDI_sync245(Module):
    def __init__(self, reset, io):
        #rst = Signal()

        # Input FIFO for reads from FT245
        self.incoming_fifo = incoming_fifo = AsyncFIFO(8, 64)
        self.submodules.incoming = ClockDomainsRenamer(
            {"write":"ftdi", "read":"sys"})(incoming_fifo)

        # Output FIFO
        self.output_fifo = output_fifo = AsyncFIFO(8, 64)
        self.submodules.outgoing = ClockDomainsRenamer(
            {"write":"sys", "read":"ftdi"})(output_fifo)

        ftdi_domain = ClockDomain("ftdi")
        ftdi_domain.rst = reset
        ftdi_domain.clk = io.clk
        # Hack
        ftdi_domain.rename("ftdi")

        self.clock_domains.cd_ftdi = ftdi_domain

        # Shared control
        # Databus is driven by both the FPGA and the FTDI
        # We use a tristate that is initially hi-z
        self.dbus = dbus = TSTriple(8)
        dbus.oe.reset = 0
        assert io.d.nbits == 8
        self.specials += dbus.get_tristate(io.d)

        io.wr_n.reset = 1
        io.rd_n.reset = 1
        io.oe_n.reset = 1
        self.comb += io.siwua_n.eq(1)

        next_RD = Signal(reset=0)
        next_WR = Signal(reset=0)
        next_OE = Signal(reset=0)
        next_dOE = Signal(reset=0)

        # Use registers for all IOs to help timing
        self.sync.ftdi += [
            io.rd_n.eq(~next_RD | io.rxf_n),
            io.oe_n.eq(~next_OE),
            dbus.oe.eq(next_dOE),
            ]



        bsf = FSM()
        
        can_write = Signal()
                
        # Try a write whenever we have data in the fifo
        self.comb += can_write.eq(~io.txe_n & output_fifo.readable)

        # Try a read whenever we have data in the FTDI fifo and nothing in the IC fifo
        can_read = Signal()
        self.comb += [
                can_read.eq(~io.rxf_n & incoming_fifo.writable),
                incoming_fifo.din.eq(dbus.i),
                dbus.o.eq(output_fifo.dout)]
        
        bsf.act('IDLE',
            # Reads from FTDI take priority over writes
            # Host must throttle reads to prevent overusage of bus BW
            If(can_read, NextState('READ'),
                next_OE.eq(1))
            .Elif(can_write, 
                NextState('I2W'),
                next_OE.eq(0)
            ))

        bsf.act('I2W',
            If(~can_write, 
                NextState('IDLE'),
                next_dOE.eq(0)
            ).Else(
                next_WR.eq(1),
                next_dOE.eq(1),

                output_fifo.re.eq(0),
                NextState('WRITE')
            )
            
        )

        bsf.act('WRITE',
                If(~can_write,
                    NextState('W2I'),
                    io.wr_n.eq(1),
                    next_dOE.eq(0),
                    output_fifo.re.eq(0)
                ).Else(
                    io.wr_n.eq(0),
                    next_dOE.eq(1),
                    output_fifo.re.eq(1),
                    next_WR.eq(1),
                    ))

        bsf.act('W2I',
                NextState('IDLE'),
                next_OE.eq(1))

        # Shitty read SM to avoid proper handshaking
        # TODO: fixup to provide higher read speads
        # Shouldn't matter timing-wise
        bsf.act('READ',
                If(can_read,
                    next_RD.eq(1),
                    next_OE.eq(1),
                    NextState('READ2')).Else(NextState('IDLE'), next_OE.eq(0))
                )
        bsf.act('READ2',
                incoming_fifo.we.eq(1),
                next_RD.eq(0),
                next_OE.eq(0),
                NextState('IDLE')
                )

        bsf.finalize()
        bsf.state.reset = bsf.encoding['IDLE']
        

        self.submodules.bsf = ClockDomainsRenamer({"sys": "ftdi"})(bsf)


        # LED Indicators for RX and TX
        self.tx_ind = Signal()
        self.rx_ind = Signal()

        self.specials += MultiReg(~io.wr_n, self.tx_ind)
        self.specials += MultiReg(~io.rd_n, self.rx_ind)
