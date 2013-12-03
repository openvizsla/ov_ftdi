from migen.fhdl.std import *
from migen.flow.actor import Source, Sink
from migen.fhdl.size import bits_for
from migen.genlib.fsm import FSM, NextState

from ovhw.ov_types import ULPI_DATA_TAG
from ovhw.constants import *
from ovhw.whacker.util import *

class Producer(Module):

    def __init__(self, wrport, depth, consume_watermark, ena, la_filters=[]):
        self.ulpi_sink = Sink(ULPI_DATA_TAG)

        self.out_addr = Source(dmatpl(depth))


        # Produce side
        self.submodules.produce_write = Acc_inc(max=depth)
        self.submodules.produce_header = Acc(max=depth)

        self.consume_point = Acc(max=depth)
        
        self.submodules.size = Acc_inc(16)
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
        pkt_timestamp = Signal(flen(self.ulpi_sink.payload.ts))
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

                    If(~(self.to_start.v | stuff_packet), self.ulpi_sink.ack.eq(1)),

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
        self.comb += packet_too_long.eq(self.size.v > 800)

        self.fsm.act("DATA",
                If(packet_too_long,
                    self.flags._or(HF0_TRUNC),
                    NextState("WRF0")
                ).Elif(has_space & self.ulpi_sink.stb,
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
                        self.produce_write.inc(),
                        wrport.adr.eq(self.produce_write.v),
                        wrport.dat_w.eq(self.ulpi_sink.payload.d),
                        wrport.we.eq(1),
                        do_filter_write.eq(1)
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
            self.out_addr.payload.count.eq(self.size.v + 8),
            If(self.out_addr.ack,
                self.produce_header.set(self.produce_write.v),
                NextState("IDLE")
            )
        )


class TestProducer(Module):
    def __init__(self):
        from migen.actorlib.sim import SimActor, Dumper, Token
        

        class PORT(Module):
            def __init__(self, aw, dw):
                self.adr = Signal(aw)
                self.dat_w = Signal(dw)
                self.we = Signal(1)

                import array
                self.mem = array.array('B', [0] * 2**aw)

            def do_simulation(self, s):
                writing, w_addr, w_data = s.multiread([self.we, self.adr, self.dat_w])
                if writing:
                    assert w_addr < 1024
                    self.mem[w_addr] = w_data


        self.submodules.port = PORT(bits_for(1024), 8)

        def packet(size=0, st=0, end=1):
            yield  Token('source', {'rxcmd':1, 'd':0x40})
            for i in range(size):
                yield  Token('source', {'rxcmd':0, 'd':(i+st)&0xFF})
            
            if end != 4:
                yield  Token('source', {'rxcmd':1, 'd':0x40 | end})

            print("Complete")

        def gen():
            for i in packet(530, 0, 1):
                yield i

            for i in packet(530, 0x10, 1):
                yield i

            for i in packet(10, 0x20, 4):
                yield i
            
            for i in packet(10, 0x30, 2):
                yield i

            for i in packet(900, 0x30, 4):
                yield i

            for i in packet(10, 0x30, 2):
                yield i

        class SimSource(SimActor):
            def __init__(self):
                self.source = Source(ULPI_DATA)
                SimActor.__init__(self, gen())

        class SimDMASink(SimActor):
            def __init__(self, mem, cw):
                self.sink = Sink(dmatpl(1024))
                SimActor.__init__(self, self.gen())

                self.mem = mem
                self.cw = cw

            def gen(self):
                import constants
                _fn = {}
                for k,v in constants.__dict__.items():
                    if k.startswith("HF0_"):
                        _fn[v] = k[4:]

                while 1:
                    t  = Token('sink')
                    yield t

                    # Long delay between packet readout
                    for i in range(600):
                        yield None
                    
                    print("DMAFROM: %04x (%02x)" % (t.value['start'], t.value['count']))


                    i = t.value['start']
                    psize = self.mem[i+3] | self.mem[i+4] << 8
                    pflags = self.mem[i+1] | self.mem[i+2] 
                    

                    e = []
                    for i in range(0,16):
                        if pflags & 1<<i and 1<<i in _fn:
                            e.append(_fn[1<<i])
                    print("\tFlag: %s" % ", ".join(e))

                    d = [self.mem[i%1024] 
                        for i in range(t.value['start'], t.value['start'] + t.value['count'])]
                    print("\t%s" % " ".join("%02x" % i for i in d))

                    assert t.value['count'] == psize + 8
                    self.s.wr(self.cw, (t.value['start'] + t.value['count']) & (1024-1))

                    b = d[8]
                    rem = d[9:]
                    c = [(i+b+1) & 0xFF for i in range(0, len(rem))]
                    assert c == rem

                    print()

            def do_simulation(self, s):
                SimActor.do_simulation(self, s)
                self.s = s



        self.consume_watermark  =Signal(max=1024)

        self.submodules.src = SimSource()
        self.submodules.p = Producer(self.port, 1024, self.consume_watermark)
        self.comb += self.p.ulpi_sink.connect(self.src.source)
        self.comb += self.src.busy.eq(0)

        self.submodules.dmp = SimDMASink(self.port.mem, self.consume_watermark)
        self.comb += self.p.out_addr.connect(self.dmp.sink)
        self.comb += self.dmp.busy.eq(0)



if __name__ == '__main__':
    from migen.sim.generic import Simulator, TopLevel
    from migen.sim.icarus import Runner
    tl = TopLevel("testprod.vcd")
    test = TestProducer()
    sim = Simulator(test, tl, Runner(keep_files=True))
    sim.run(8000)
    

        
