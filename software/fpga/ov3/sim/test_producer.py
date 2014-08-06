import unittest

from migen.fhdl.std import *
from migen.fhdl.bitcontainer import bits_for
from migen.flow.actor import Source, Sink
from migen.actorlib.sim import SimActor, Dumper, Token
from migen.sim.generic import Simulator, TopLevel

from ovhw.ov_types import ULPI_DATA_TAG

from ovhw.constants import *
from ovhw.whacker.producer import Producer, MAX_PACKET_SIZE
from ovhw.whacker.util import *

class TestBench(Module):
    def __init__(self):
        class PORT(Module):
            def __init__(self, aw, dw):
                self.adr = Signal(aw)
                self.dat_w = Signal(dw)
                self.we = Signal(1)

                import array
                self.mem = array.array('B', [0] * 2**aw)

            def do_simulation(self, selfp):
                writing, w_addr, w_data = selfp.we, selfp.adr, selfp.dat_w
                if writing:
                    assert w_addr < 1024
                    self.mem[w_addr] = w_data


        self.submodules.port = PORT(bits_for(1024), 8)

        def _deferred_source_gen():
            yield
            yield from self.src_gen

        def _deferred_sink_gen():
            yield
            yield from self.sink_gen

        class SimSource(SimActor):
            def __init__(self):
                self.source = Source(ULPI_DATA_TAG)
                SimActor.__init__(self, _deferred_source_gen())

        class SimDMASink(SimActor):
            def __init__(self):
                self.sink = Sink(dmatpl(1024))
                SimActor.__init__(self, _deferred_sink_gen())

        self.consume_watermark  =Signal(max=1024)

        self.submodules.src = SimSource()
        self.submodules.p = Producer(self.port, 1024, self.consume_watermark, 1)
        self.comb += self.p.ulpi_sink.connect(self.src.source)
        self.comb += self.src.busy.eq(0)

        self.submodules.dmp = SimDMASink()
        self.comb += self.p.out_addr.connect(self.dmp.sink)
        self.comb += self.dmp.busy.eq(0)

    def do_simulation(self, selfp):
        self.selfp = selfp

    
    def packet(self, size=0, st=0, end=1, timestamp=0):
        def _(**kwargs):
            jj = {"is_start":0, "is_end":0, "is_ovf":0, "is_err":0,
                  "d":0,"ts":0}
            jj.update(kwargs)
            return jj

        yield  Token('source', _(is_start=1, ts=timestamp))
        for i in range(size):
            yield  Token('source', _(d=(i+st)&0xFF))
        
        yield  Token('source', _(is_end=1))

class TestProducer(unittest.TestCase):
    def setUp(self):
        self.tb = TestBench()
        self.sim = Simulator(self.tb, TopLevel("test_producer.vcd", vcd_level = 3))

    def _run(self):
        with self.sim as sim:
            sim.run(8000)

    def test_producer(self):
        seq = [
            (530, 0, 1, 0xCAFEBA),
            (530, 0x10, 1, 0xCDEF0),
            (10, 0x20, 4, 0xDE0000),
            (10, 0x30, 2, 0xDF0123),
            (900, 0x30, 4, 0xE10320),
            (10, 0x30, 2, 0xE34567)
        ]

        def src_gen():
            for p in seq:
                yield from self.tb.packet(*p)

        self.tb.src_gen = src_gen()


        # Build a reverse-mapping from bits to constant names
        import ovhw.constants
        flag_names = {}
        for k,v in ovhw.constants.__dict__.items():
            if k.startswith("HF0_"):
                flag_names[v] = k[4:]


        def sink_get_packet(sub_len, sub_base, sub_flags, timestamp):
            # Expected payload length
            calc_len = sub_len if sub_len < MAX_PACKET_SIZE else MAX_PACKET_SIZE
            
            t = Token('sink')
            yield t

            # Long delay before packet readout to simulate blocked
            # SDRAM
            for i in range(600):
                yield None
            
            print("DMAFROM: %04x (%02x)" % (t.value['start'], t.value['count']))

            mem = self.tb.port.mem

            # Read packet header
            i = t.value['start']
            p_magic = mem[i]
            p_flags = mem[i+1] | mem[i+2] 
            p_size = mem[i+3] | mem[i+4] << 8
            p_timestamp = mem[i+5] | mem[i+6] << 8 | mem[i+7] << 16

            # Check that the packet header we read out was what we were
            # expecting
            self.assertEqual(p_magic, 0xA0)
            self.assertEqual(p_size, calc_len)
            self.assertEqual(p_timestamp, timestamp)

            # Check that the DMA request matched the packet
            self.assertEqual(t.value['count'], calc_len + 8)

            # Build and print the flags
            flag_names = []
            for i in range(0,16):
                if p_flags & 1<<i and 1<<i in flag_names:
                    e.append(flag_names[1<<i])
            print("\tFlag: %s" % ", ".join(flag_names))

            # Fetch and print the body
            packet = []
            for i in range(t.value['start'], t.value['start'] +
                           t.value['count']):
                packet.append(mem[i%1024])
                yield
            print("\t%s" % " ".join("%02x" % i for i in packet))

            # Update the producer watermark
            self.tb.selfp.consume_watermark = (t.value['start'] + t.value['count']) & (1024-1)

            # Check the payload matches
            expected_payload = [(sub_base+i) & 0xFF for i in range(0, calc_len)]
            self.assertEqual(expected_payload, packet[8:])

        def sink_gen():
            yield from sink_get_packet(0, 0, 0x10, 0)
            for p in seq:
                yield from sink_get_packet(*p)

        self.tb.sink_gen = sink_gen()


        self._run()


if __name__ == '__main__':
    unittest.main()
        
