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
                 tRESET, tCL, tRP, tRFC, tREFI):
        _FIFOInterface.__init__(self, databits, None)

        addrbits = rowbits + colbits + bankbits
        assert sdram.dq.nbits == databits
        colabits = colbits if colbits <= 10 else colbits + 1
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
        # These are not registers, they are functions of the current FSM state.
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
        self.comb += [
            sdram.dqm.eq(Replicate(dqm, dqmbits)),
            sdram.cs_n.eq(cmd[3]),
            sdram.ras_n.eq(cmd[2]),
            sdram.cas_n.eq(cmd[1]),
            sdram.we_n.eq(cmd[0]),
            sdram.clk.eq(clk_out),
            sdram.ba.eq(ba),
            sdram.a.eq(a),
            sdram.cke.eq(cke),
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
        fsm.act("IDLE")
