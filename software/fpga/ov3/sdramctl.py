from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState, AnonymousState
from migen.genlib.record import Record
from ov_types import sdramHostIf

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


class SDRAMCTL(Module):
    def __init__(self, sdram, clk_out, clk_sample,
                 databits, rowbits, colbits, bankbits,
                 burst,
                 tRESET, tCL, tRP, tRFC, tRCD, tREFI, tWR):

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

        self.hostif = Record(sdramHostIf(databits, addrbits))

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

        sdram.cs_n.reset = 1
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

        # last_col indicates that the read/write is about to wrap, and so should end
        last_col = Signal()
        i_col_cnt = Signal(colbits)
        self.comb += last_col.eq(i_col_cnt == max_col)

        def delay_clocks(v, d):
            for i in range(d):
                n = Signal()
                self.sync += n.eq(v)
                v = n
            return v

        # Read cycle state signals
        read_cycle = Signal()

        # Reads come back tCL + 1 clocks later. The extra cycle
        # is due to the registration of FIFO outputs
        returning_read = delay_clocks(read_cycle, tCL + 1)
        can_continue_read = Signal()
        kill_read = Signal()
        self.comb += [
            can_continue_read.eq(~self.hostif.d_term & ~last_col & ~kill_read),

            self.hostif.d_read.eq(dq_r),
        ]
        self.sync += [
            # If the output FIFO becomes full, kill the current read
            If(returning_read & self.hostif.d_term,
               kill_read.eq(1)
            ).Elif(~returning_read,
               kill_read.eq(0)
            ),
        ]

        # Write state signals
        write_cycle = Signal()
        can_continue_write = Signal()

        self.sync += [
            dq.o.eq(self.hostif.d_write),
            dq.oe.eq(write_cycle),
        ]

        self.comb += [
            can_continue_write.eq(~self.hostif.d_term & ~last_col),
            dqm.eq(self.hostif.d_term & write_cycle),
        ]

        # Shared signals
        cmd_needs_reissue = Signal()
        cmd_reissue = Signal()


        self.sync += [
            If(write_cycle | read_cycle, i_col_cnt.eq(i_col_cnt + 1)),
            If(~self.hostif.d_term & last_col & write_cycle | 
               read_cycle & last_col & ~kill_read & ~(returning_read & self.hostif.d_term),
               cmd_needs_reissue.eq(1)).Elif(cmd_reissue, cmd_needs_reissue.eq(0))
               
        ]

        # Hostif streaming interface signal generation
        self.comb += [
            self.hostif.d_stb.eq(write_cycle | returning_read & ~kill_read),
            ]

        # Address generation
        def split(addr):
            col = addr[:colbits]
            if colbits > 10:
                col = Cat(col[:10],0,col[10:])
            return col, addr[colbits:colbits+rowbits], addr[colbits+rowbits:]

        # Issued cmd ptr
        latch_cmd = Signal()
        iwr = Signal(1)
        iptr = Signal(addrbits)
        i_col, i_row, i_bank = split(iptr)

        self.sync += If(latch_cmd,
            iptr.eq(self.hostif.i_addr),
            iwr.eq(self.hostif.i_wr),
            i_col_cnt.eq(split(self.hostif.i_addr)[0])
        ).Elif(cmd_reissue,
            iptr[:colbits].eq(0),
            iptr[colbits:].eq(iptr[colbits:] + 1),
            i_col_cnt.eq(0)
        )


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
                        ).Elif(cmd_needs_reissue,
                            cmd_reissue.eq(1),
                            If(iwr, 
                                NextState("WRITE_ACTIVE")
                            ).Else(
                                NextState("READ_ACTIVE")
                            )
                        ).Elif(self.hostif.i_wr & self.hostif.i_stb,
                            self.hostif.i_ack.eq(1),
                            latch_cmd.eq(1),
                            NextState("WRITE_ACTIVE")
                        ).Elif(~self.hostif.i_wr & self.hostif.i_stb,
                            self.hostif.i_ack.eq(1),
                            latch_cmd.eq(1),
                            NextState("READ_ACTIVE")
                        ))
        # REFRESH
        fsm.act("REFRESH", cmd.eq(AUTO_REFRESH))
        fsm.delayed_enter("REFRESH", "IDLE", tRFC)

        # WRITE
        fsm.act("WRITE_ACTIVE", cmd.eq(ACTIVE), ba.eq(i_bank), a.eq(i_row))
        fsm.delayed_enter("WRITE_ACTIVE", "WRITE", tRCD)
        fsm.act("WRITE", cmd.eq(WRITE), ba.eq(i_bank), a.eq(i_col),
                write_cycle.eq(1), 
                If(can_continue_write,
                   NextState("WRITING")
                ).Else(
                    If(dqm,
                        NextState("PRECHARGE")
                    ).Else(
                        NextState("PRECHARGE_TWR")
                    )
                ))
        fsm.act("WRITING", write_cycle.eq(1),
                If(~can_continue_write,
                    If(dqm,
                        NextState("PRECHARGE")
                    ).Else(
                        NextState("PRECHARGE_TWR")
                    )
                   ))

        # READ
        fsm.act("READ_ACTIVE", cmd.eq(ACTIVE), ba.eq(i_bank), a.eq(i_row))
        fsm.delayed_enter("READ_ACTIVE", "READ", tRCD)
        fsm.act("READ", cmd.eq(READ), ba.eq(i_bank), a.eq(i_col),
                read_cycle.eq(1),
                If(can_continue_read,
                   NextState("READING")
                ).Else(
                   NextState("PRECHARGE")))
        fsm.act("READING", read_cycle.eq(1),
                If(~can_continue_read,
                   NextState("PRECHARGE")))

        if (tWR - 1) > 0:
            fsm.act("PRECHARGE_TWR", cmd.eq(BURST_TERM))

        fsm.delayed_enter("PRECHARGE_TWR", "PRECHARGE", tWR-1),
        fsm.act("PRECHARGE", cmd.eq(PRECHARGE), a[10].eq(1)),
        fsm.delayed_enter("PRECHARGE", "IDLE", tRP)



