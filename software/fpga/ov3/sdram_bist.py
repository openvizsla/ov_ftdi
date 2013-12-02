from migen.fhdl.std import *
from migen.genlib.fsm import FSM, NextState

TEST_ALT0 = 0   # 0000/FFFF
TEST_ALT1 = 1   # AAAA/5555
TEST_LFSR = 2   # LFSR
TEST_ADDR = 3   # ADDR
TEST_ZERO = 4   # 0000
TEST_ONES = 5   # FFFF

class SdramBist(Module):
    def __init__(self, hostif, mem_size):
        width = flen(hostif.d_write)
        assert width == 16

        self.start = Signal()
        self.sel_test = Signal(4)
        self.busy = Signal()

        self.lat_test = Signal(4)

        self.ok = Signal()

        self.status = Signal()

        self.submodules.fsm = FSM()
        self.comb += self.busy.eq(~self.fsm.ongoing("IDLE"))
        pat = Signal(width)

        
        self.lfsr = Signal(32)

        self.sync += [
            If(self.fsm.ongoing("IDLE") & self.start,
               self.lat_test.eq(self.sel_test),
               self.ok.eq(1),
              ).Elif((self.fsm.ongoing("WAIT_ISSUE_READ") |
                     self.fsm.ongoing("READ")) & hostif.d_stb &
                     (hostif.d_read != pat),
                     self.ok.eq(0))

                ]

        # Address calculation
        self.addr = Signal(max=mem_size)

        reset_addr = Signal()
        self.sync += If(reset_addr,
            self.addr.eq(0),
        ).Elif(hostif.d_stb,
            self.addr.eq(self.addr + 1)
        )

        # Pattern derivation

        self.comb += [
            Case(self.lat_test, {
                TEST_ALT0: pat.eq(Replicate(self.addr[0], width)),
                TEST_ALT1: pat.eq(Replicate(self.addr[0], width) ^ 0xAAAA),
                TEST_LFSR: pat.eq(0), # STUB
                TEST_ADDR: pat.eq(self.addr[:width]),
                TEST_ZERO: pat.eq(0),
                TEST_ONES: pat.eq(0xFFFF)
            }),

            If(self.fsm.ongoing("WRITE") | self.fsm.ongoing("WAIT_ISSUE_WR"),
                hostif.d_write.eq(pat)
              )
        ]

        lastaddr = self.addr == (mem_size - 1)



        self.fsm.act("IDLE",
            If(self.start,
               reset_addr.eq(1),
               NextState("WAIT_ISSUE_WR")
              ))

        self.fsm.act(
            "WAIT_ISSUE_WR",
            hostif.i_wr.eq(1),
            hostif.i_stb.eq(1),
            hostif.i_addr.eq(0),

            If(hostif.i_ack,
               NextState("WRITE")
            )
        )

        self.fsm.act(
            "WRITE",
            If(lastaddr & hostif.d_stb,
               NextState("WRITE-TERM")
              )
        )

        self.fsm.act(
            "WRITE-TERM",
            hostif.d_term.eq(1),
            If(hostif.d_stb,
               reset_addr.eq(1),
               NextState("WAIT_ISSUE_READ")
              ))

        self.fsm.act(
            "WAIT_ISSUE_READ",
            hostif.i_wr.eq(0),
            hostif.i_stb.eq(1),
            hostif.i_addr.eq(0),

            If(hostif.i_ack,
                NextState("READ")
              ))
        self.fsm.act(
            "READ",
            If(lastaddr & hostif.d_stb,
               NextState("READ-TERM"))
        )
        self.fsm.act(
            "READ-TERM",
            hostif.d_term.eq(1),
            If(hostif.d_stb,
               NextState("IDLE")
              ))



