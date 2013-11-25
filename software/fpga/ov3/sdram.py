from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState, AnonymousState
from migen.genlib.fifo import _FIFOInterface, AsyncFIFO

#                   CS# RAS# CAS# WE# DQM ADDR DQ
# COMMAND INHIBIT     1    x    x   x   x    x  x
# NOP                 0    1    1   1   x    x  x
# ACTIVE              0    0    1   1   x  ROW  x
# READ                0    1    0   1  01  COL  x       A10=auto precharge
# WRITE               0    1    0   0  01  COL  Valid   A10=auto precharge
# BURST TERMINATE     0    1    1   0   x    x  Active
# PRECHARGE           0    0    1   0   x  COD  x       A10=all banks
# AUTO REFRESH        0    0    0   1   x    x  x
# LOAD MODE REG       0    0    0   0   x  OPC  x
# Write enable/OE     x    x    x   x   0    x  Active
# Write inhibit/HZ    x    x    x   x   1    x  HZ

INHIBIT = 0b1000
NOP = 0b0111
ACTIVE = 0b0011
READ = 0b0101
WRITE = 0b0100
BURST_TERM = 0b0110
PRECHARGE = 0b0010
AUTO_REFRESH = 0b0001
LOAD_MODE = 0b0000

# Clock domains:
# sys: core clock for the SDRAM.
# read: clock domain of the read port
# write: clock domain of the write port
#
# Extra clocks:
# clk_out: clock signal output to the SDRAM. Should be about 180 degrees out of
#          phase with the sys clock domain
# clk_sample: sampling clock for SDRAM->FPGA data. Should be about 180 degrees
#          out of phase with the sys clock domain, perhaps a bit more
#          (frequency dependent).
class SDRAMFIFO(Module):
    def __init__(self, sdram, clk_out, clk_sample,
                 databits, rowbits, colbits, bankbits,
                 inbuf, outbuf, burst,
                 tRESET, tCL, tRP, tRFC, tRCD, tREFI):
        _FIFOInterface.__init__(self, databits, None)

        addrbits = rowbits + colbits + bankbits
        assert sdram.dq.nbits == databits
        colabits = colbits if colbits <= 10 else colbits + 1
        max_col = Replicate(1, colbits)
        assert sdram.a.nbits >= colabits
        assert sdram.a.nbits >= rowbits
        assert sdram.ba.nbits == bankbits
        dqmbits = max(databits // 8, 1)
        assert sdram.dqm.nbits == dqmbits
        assert burst <= 1<<colbits

        # DQ handling, tristate, and sampling
        dq = TSTriple(databits)
        self.specials += dq.get_tristate(sdram.dq)
        dq_r = Signal(databits)
        self.clock_domains.cd_sample = ClockDomain(reset_less=True)
        self.comb += self.cd_sample.clk.eq(clk_sample)
        self.sync.sample += dq_r.eq(dq.i)

        # Signals used for driving SDRAM control signals
        # These registered and derived from the current FSM state.
        # However, the reset state actually determines the default value for
        # states where they are not explicitly assigned. For example, cmd is
        # INHIBIT at reset (because the FSM is in RESET state at reset and that
        # sets cmd to INHIBIT), but it's NOP for every other state where it
        # isn't assigned.
        cmd = Signal(4, reset=NOP)
        dqm = Signal()
        ba = Signal(bankbits)
        a = Signal(max(colabits, rowbits))
        cke = Signal()
        self.sync += [
            sdram.dqm.eq(Replicate(dqm, dqmbits)),
            sdram.cs_n.eq(cmd[3]),
            sdram.ras_n.eq(cmd[2]),
            sdram.cas_n.eq(cmd[1]),
            sdram.we_n.eq(cmd[0]),
            sdram.ba.eq(ba),
            sdram.a.eq(a),
            sdram.cke.eq(cke),
        ]
        self.comb += [
            sdram.clk.eq(clk_out),
        ]

        # Counter to time reset cycle of the SDRAM
        # We enable CKE on the first cycle after system reset, then wait tRESET
        reset_ctr = Signal(max=tRESET+1)
        self.sync += [
            cke.eq(1),
            reset_ctr.eq(reset_ctr + 1)
        ]

        # Counter to time refresh intervals
        # Note that this can go higher than tREFI, since we might be in the
        # middle of a burst, but long-term refresh cycles will be issued often
        # enough to meet refresh timing.
        refresh_interval = tREFI - 2  # A bit of leeway for safety
        refresh_ctr = Signal(max=(refresh_interval + 2*burst + 128))
        self.sync += If(cmd == AUTO_REFRESH,
                        If(refresh_ctr > refresh_interval,
                           refresh_ctr.eq(refresh_ctr - refresh_interval)
                        ).Else(
                           refresh_ctr.eq(0))
                     ).Else(
                        refresh_ctr.eq(refresh_ctr + 1))

        tMRD = 3  # JEDEC spec, Micron only needs 2
        # Mode: Full page burst mode, burst write
        mode = 0b0000000111 | (tCL << 4)

        # FIFOs
        fifo_in = RenameClockDomains(AsyncFIFO(databits, inbuf),
                                     {"read": "sys"})
        fifo_out = RenameClockDomains(AsyncFIFO(databits, outbuf),
                                      {"write": "sys"})
        self.submodules += [fifo_in, fifo_out]
        self.comb += [
            # Wire up FIFO ports to module interface
            self.writable.eq(fifo_in.writable),
            fifo_in.din.eq(self.din_bits),
            fifo_in.we.eq(self.we),
            self.readable.eq(fifo_out.readable),
            fifo_out.re.eq(self.re),
            self.dout_bits.eq(fifo_out.dout),
        ]

        # SDRAM FIFO pointer regs
        write_ptr = Signal(addrbits)
        read_ptr = Signal(addrbits)
        read_ptr_shadow = Signal(addrbits)

        def delay_clocks(v, d):
            for i in range(d):
                n = Signal()
                self.sync += n.eq(v)
                v = n
            return v

        # Read cycle state signals
        issuing_read = Signal()

        # Reads come back tCL + 1 clocks later. The extra cycle
        # is due to the registration of FIFO outputs
        returning_read = delay_clocks(issuing_read, tCL + 1)
        can_read = Signal()
        can_continue_read = Signal()
        kill_read = Signal()
        self.comb += [
            can_read.eq((write_ptr != read_ptr) & fifo_out.writable),
            can_continue_read.eq((write_ptr != read_ptr_shadow + 1) &
                                 fifo_out.writable &
                                 (read_ptr_shadow[:colbits] != max_col) &
                                 ~kill_read),

            fifo_out.din.eq(dq_r),
            fifo_out.we.eq(returning_read & ~kill_read),
        ]
        self.sync += [
            # Increment read pointer when data is written to output FIFO
            If(fifo_out.we & fifo_out.writable,
               read_ptr.eq(read_ptr + 1)),
            # Keep a shadow read pointer for issuing reads. Increment it
            # while a read is being issued, but reset it to the true read
            # otherwise (which might be different if a read was killed).
            If(~issuing_read,
               read_ptr_shadow.eq(read_ptr),
            ).Else(
               read_ptr_shadow.eq(read_ptr_shadow + 1),
            ),
            # If the output FIFO becomes full, kill the current read
            If(returning_read & ~fifo_out.writable,
               kill_read.eq(1)
            ).Elif(~returning_read,
               kill_read.eq(0)
            ),
        ]

        # Write state signals
        issuing_write = Signal()
        can_write = Signal()
        can_continue_write = Signal()

        self.sync += [
            dq.o.eq(fifo_in.dout),
            dq.oe.eq(issuing_write),
        ]

        self.comb += [
            can_write.eq((write_ptr + 1 != read_ptr) & fifo_in.readable),
            can_continue_write.eq((write_ptr + 2 != read_ptr) &
                                  fifo_in.readable &
                                  (write_ptr[:colbits] != max_col)),

            fifo_in.re.eq(issuing_write),
        ]
        self.sync += [
            # Increment write pointer when data is read from input FIFO
            If(fifo_in.re & fifo_in.readable,
               write_ptr.eq(write_ptr + 1)),
        ]

        # Address generation
        def split(addr):
            col = addr[:colbits]
            if colbits > 10:
                col = Cat(col[:10],0,col[10:])
            return col, addr[colbits:colbits+rowbits], addr[colbits+rowbits:]

        r_col, r_row, r_bank = split(read_ptr)
        w_col, w_row, w_bank = split(write_ptr)

        # Finite state machine driving the controller
        fsm = self.submodules.fsm = FSM(reset_state="RESET")

        # Initialization sequence
        fsm.act("RESET",
                cmd.eq(INHIBIT),
                If(reset_ctr == tRESET, NextState("INIT_IDLE")))
        fsm.delayed_enter("INIT_IDLE", "INIT_PRECHARGE", 5)
        fsm.act("INIT_PRECHARGE", cmd.eq(PRECHARGE), a[10].eq(1))
        fsm.delayed_enter("INIT_PRECHARGE", "INIT_REFRESH1", tRP)
        fsm.act("INIT_REFRESH1", cmd.eq(AUTO_REFRESH))
        fsm.delayed_enter("INIT_REFRESH1", "INIT_REFRESH2", tRFC)
        fsm.act("INIT_REFRESH2", cmd.eq(AUTO_REFRESH))
        fsm.delayed_enter("INIT_REFRESH2", "INIT_MODE", tRFC)
        fsm.act("INIT_MODE", cmd.eq(LOAD_MODE), a.eq(mode))
        fsm.delayed_enter("INIT_MODE", "IDLE", tMRD)

        # Main loop
        fsm.act("IDLE", If(refresh_ctr >= refresh_interval,
                           NextState("REFRESH")
                        ).Elif(can_write,
                           NextState("WRITE_ACTIVE")
                        ).Elif(can_read,
                           NextState("READ_ACTIVE")
                        ))
        # REFRESH
        fsm.act("REFRESH", cmd.eq(AUTO_REFRESH))
        fsm.delayed_enter("REFRESH", "IDLE", tRFC)

        # WRITE
        fsm.act("WRITE_ACTIVE", cmd.eq(ACTIVE), ba.eq(w_bank), a.eq(w_row))
        fsm.delayed_enter("WRITE_ACTIVE", "WRITE", tRCD)
        fsm.act("WRITE", cmd.eq(WRITE), ba.eq(w_bank), a.eq(w_col),
                issuing_write.eq(1), dqm.eq(~fifo_in.readable),
                If(can_continue_write,
                   NextState("WRITING")
                ).Else(
                   If(can_read,
                      NextState("PRECHARGE_AND_READ")
                   ).Else(
                      NextState("PRECHARGE")
                   )))
        fsm.act("WRITING", issuing_write.eq(1), dqm.eq(~fifo_in.readable),
                If(~can_continue_write,
                   If(can_read,
                      NextState("PRECHARGE_AND_READ")
                   ).Else(
                      NextState("PRECHARGE")
                   )))
        fsm.act("PRECHARGE_AND_READ", cmd.eq(PRECHARGE), a[10].eq(1)),
        fsm.delayed_enter("PRECHARGE_AND_READ", "READ_ACTIVE", tRP)

        # READ
        fsm.act("READ_ACTIVE", cmd.eq(ACTIVE), ba.eq(r_bank), a.eq(r_row))
        fsm.delayed_enter("READ_ACTIVE", "READ", tRCD)
        fsm.act("READ", cmd.eq(READ), ba.eq(r_bank), a.eq(r_col),
                issuing_read.eq(1),
                If(can_continue_read,
                   NextState("READING")
                ).Else(
                   NextState("PRECHARGE")))
        fsm.act("READING", issuing_read.eq(1),
                If(~can_continue_read,
                   NextState("PRECHARGE")))
        fsm.act("PRECHARGE", cmd.eq(PRECHARGE), a[10].eq(1)),
        fsm.delayed_enter("PRECHARGE", "IDLE", tRP)

class FakeSDRAM(Module):
    CMD_MAP = {
        (1,0,0,0): "INHIBIT",
        (0,1,1,1): "NOP",
        (0,0,1,1): "ACTIVE",
        (0,1,0,1): "READ",
        (0,1,0,0): "WRITE",
        (0,1,1,0): "BURST_TERM",
        (0,0,1,0): "PRECHARGE",
        (0,0,0,1): "AUTO_REFRESH",
        (0,0,0,0): "LOAD_MODE",
    }
    def __init__(self):
        self.clk = Signal()
        self.a = Signal(13)
        self.ba = Signal(2)
        self.cs_n = Signal()
        self.cke = Signal()
        self.ras_n = Signal()
        self.cas_n = Signal()
        self.we_n = Signal()
        self.dq = Signal(16)
        self.dqm = Signal(2)

    def do_simulation(self, s):
        cmd = s.rd(self.cs_n), s.rd(self.ras_n), s.rd(self.cas_n), s.rd(self.we_n)
        print("%12s CKE[%01x] A[%04x] BA[%01x] DQM[%01x] DQ[%04x]" % (
            self.CMD_MAP[cmd], s.rd(self.cke), s.rd(self.a), s.rd(self.ba),
            s.rd(self.dqm), s.rd(self.dq)
        ))

class TestSDRAM(Module):
    def __init__(self, clock):
        self.submodules.fakesdram = FakeSDRAM()
        self.clock_domains.inv = ClockDomain()
        self.inv.clk = Signal()
        self.comb += self.inv.clk.eq(clock.clk)
        self.inv.rst = clock.rst
        self.submodules.sdram = RenameClockDomains(
            SDRAMFIFO(self.fakesdram,
                      clk_out=clock.clk,
                      clk_sample=clock.clk,
                      databits=16, rowbits=13, colbits=9, bankbits=2,
                      inbuf=32, outbuf=32, burst=512,
                      tRESET=20, tCL=3, tRP=4, tRFC=12, tRCD=4,
                      tREFI=780),
            {"read": "inv", "write": "inv", "sys": "inv"})

        # Test the SDRAM: write incrementing 16-bit words
        word_ctr = Signal(16)
        self.sync.inv += If(self.sdram.writable & self.sdram.we,
                            word_ctr.eq(word_ctr + 1))
        div = Signal(16)
        self.sync.inv += div.eq(div+1)
        self.comb += [
            self.sdram.we.eq(div[0:2] == 0),
            self.sdram.din.eq(word_ctr),
        ]

        # Read back and do nothing
        self.comb += [
            self.sdram.re.eq(1),
        ]
    def do_simulation(self, s):
        if s.rd(self.sdram.re) and s.rd(self.sdram.readable):
            print("GET %04x" % s.rd(self.sdram.dout))
        if s.rd(self.sdram.we) and s.rd(self.sdram.writable):
            print("PUT %04x" % s.rd(self.sdram.din))


if __name__ == "__main__":
    from migen.sim.generic import Simulator, TopLevel
    tl = TopLevel("sdram.vcd")
    test = TestSDRAM(tl.clock_domains[0])
    sim = Simulator(test, tl)
    sim.run(5000)
