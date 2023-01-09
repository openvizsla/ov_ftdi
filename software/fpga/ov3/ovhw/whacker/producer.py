from migen import *
from misoc.interconnect.stream import Endpoint
from migen.fhdl.bitcontainer import bits_for
from migen.genlib.fsm import FSM, NextState

from ovhw.ov_types import ULPI_DATA_TAG
from ovhw.constants import *
from ovhw.whacker.util import *

MAX_PACKET_SIZE = 800
class Producer(Module):

    def __init__(self, wrport, depth, consume_watermark, ena, la_filters=[]):
        self.ulpi_sink = Endpoint(ULPI_DATA_TAG)

        self.out_addr = Endpoint(dmatpl(depth))


        # Produce side
        self.submodules.produce_write = Acc_inc(max=depth)
        self.submodules.produce_header = Acc(max=depth)

        self.consume_point = Acc(max=depth)
        
        self.submodules.size = Acc_inc_sat(16)
        self.submodules.flags = Acc_or(16)

        self.submodules.to_start = Acc(1)

        # Header format:
        # A0 F0 F1 SL SH 00 00 00 d0....dN

        # Flags format
        # 
        # F0.0 - ERR  - Line level error (ULPI.RXERR asserted during packet)
        # F0.1 - OVF  - RX Path Overflow (shouldn't happen - debugging)
        # F0.2 - CLIP - Filter clipped (we do not set yet)
        # F0.3 - PERR - Protocol level err (but ULPI was fine, ???)
        #
        # Following not implemented yet
        # F0.6 - SHORT - short packet, no size, fixed 4 byte data
        # F0.7 - EXT   - Extended header
        self.submodules.fsm = FSM()

        has_space = Signal()

        self.comb += has_space.eq(((consume_watermark - self.produce_write.v - 1) & (depth - 1)) > 8)

        # Grab packet timestamp at SOP
        pkt_timestamp = Signal(len(self.ulpi_sink.payload.ts))
        self.sync += If(self.ulpi_sink.payload.is_start & self.ulpi_sink.ack,
                pkt_timestamp.eq(self.ulpi_sink.payload.ts))


        payload_is_rxcmd = Signal()
        self.comb += payload_is_rxcmd.eq(
            self.ulpi_sink.payload.is_start | 
            self.ulpi_sink.payload.is_end | 
            self.ulpi_sink.payload.is_err |
            self.ulpi_sink.payload.is_ovf)

        # Packet first/last bits
        clear_acc_flags = Signal()

        en_last = Signal()
        self.sync += en_last.eq(ena)
        self.submodules.packet_first = Acc(1)
        self.submodules.packet_last = Acc(1)

        # Stuff-packet bit
        # At start-of-capture or end-of-capture, we stuff a packet to
        # indicate the exact time of capture
        stuff_packet = Signal()
        self.comb += stuff_packet.eq(self.packet_first.v | self.packet_last.v)

        self.comb += If(ena & ~en_last, 
            self.packet_first.set(1)).Elif(clear_acc_flags,
            self.packet_first.set(0))

        self.comb += If(~ena & en_last, 
            self.packet_last.set(1)).Elif(clear_acc_flags,
            self.packet_last.set(0))

        flags_ini = Signal(16)
        self.comb += flags_ini.eq(
            Mux(self.packet_last.v, HF0_LAST, 0) |
            Mux(self.packet_first.v, HF0_FIRST, 0)
            )


        # Combine outputs of filters
        la_resets = [f.reset.eq(1) for f in la_filters]
        filter_done = 1
        filter_reject = 0
        for f in la_filters:
            filter_done = f.done & filter_done
            filter_reject = f.reject | filter_reject

        self.fsm.act("IDLE",
                If(
                    ((self.ulpi_sink.stb | self.to_start.v) & ena 
                     | stuff_packet) & has_space,

                    If(~self.to_start.v | (self.ulpi_sink.stb & stuff_packet), self.ulpi_sink.ack.eq(1)),

                    self.produce_write.set(self.produce_header.v+8),
                    self.size.set(0),
                    self.flags.set(flags_ini),
                    self.to_start.set(0),

                    la_resets,
                    
                    If(self.ulpi_sink.payload.is_start | self.to_start.v,
                        NextState("DATA")

                    ).Elif(stuff_packet,
                        NextState("WH0"),
                        clear_acc_flags.eq(1),
                    )

                # If not enabled, we just dump RX'ed data
                ).Elif(~ena,
                    self.ulpi_sink.ack.eq(1)
                )
        )

        def write_hdr(statename, nextname, hdr_offs, val):
            self.fsm.act(statename, 
                    NextState(nextname),
                    wrport.adr.eq(self.produce_header.v + hdr_offs),
                    wrport.dat_w.eq(val),
                    wrport.we.eq(1)
                    )
        

        do_filter_write = Signal()

        # Feed data to lookaside filters
        for f in la_filters:
            self.comb += [
                f.write.eq(do_filter_write),
                f.dat_w.eq(self.ulpi_sink.payload)
            ]
            
        packet_too_long = Signal()
        self.comb += packet_too_long.eq(self.size.v >= MAX_PACKET_SIZE)

        self.fsm.act("DATA",
                If(has_space & self.ulpi_sink.stb,
                    self.ulpi_sink.ack.eq(1),
                    If(payload_is_rxcmd,

                        # Got another start-of-packet
                        If(self.ulpi_sink.payload.is_start,
                            self.flags._or(HF0_OVF),

                            # If we got a SOP, we need to skip RXCMD det in IDLE
                            self.to_start.set(1)

                        # Mark error if we hit an error
                        ).Elif(self.ulpi_sink.payload.is_err,
                            self.flags._or(HF0_ERR),

                        # Mark overflow if we got a stuffed overflow
                        ).Elif(self.ulpi_sink.payload.is_ovf,
                            self.flags._or(HF0_OVF)
                        ),

                        # In any case (including END), we're done RXing
                        NextState("waitdone")
                    ).Else(
                        self.size.inc(),
                        If(packet_too_long,
                            self.flags._or(HF0_TRUNC)
                        ).Else(
                            self.produce_write.inc(),
                            wrport.adr.eq(self.produce_write.v),
                            wrport.dat_w.eq(self.ulpi_sink.payload.d),
                            wrport.we.eq(1),
                            do_filter_write.eq(1)
                        )
                    )
                )
            )
        

        self.fsm.act("waitdone",
                If(filter_done,
                    If(filter_reject,
                        NextState("IDLE")
                    ).Else(
                        clear_acc_flags.eq(1),
                        NextState("WH0"))
                ))

        write_hdr("WH0", "WRF0", 0, 0xA0)

        # Write flags field
        write_hdr("WRF0", "WRF1", 1, self.flags.v[:8])
        write_hdr("WRF1", "WRSL", 2, self.flags.v[8:16])

        # Write size field
        write_hdr("WRSL", "WRSH", 3, self.size.v[:8])
        write_hdr("WRSH", "WRTL", 4, self.size.v[8:16])

        write_hdr("WRTL", "WRTM", 5, pkt_timestamp[:8])
        write_hdr("WRTM", "WRTH", 6, pkt_timestamp[8:16])
        write_hdr("WRTH", "SEND", 7, pkt_timestamp[16:24])

        self.fsm.act("SEND",
            self.out_addr.stb.eq(1),
            self.out_addr.payload.start.eq(self.produce_header.v),
            If(packet_too_long,
                self.out_addr.payload.count.eq(MAX_PACKET_SIZE + 8)
            ).Else(
                self.out_addr.payload.count.eq(self.size.v + 8),
            ),
            If(self.out_addr.ack,
                self.produce_header.set(self.produce_write.v),
                NextState("IDLE")
            )
        )

