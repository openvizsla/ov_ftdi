from migen import *
from misoc.interconnect.stream import Endpoint
from migen.sim.generic import Simulator
from migen.actorlib.sim import SimActor, Dumper, Token

from ovhw.whacker.consumer import Consumer
from ovhw.whacker.util import dmatpl

from ovhw.ov_types import D_LAST, ULPI_DATA_D

import unittest

class TestBench(Module):
    def __init__(self):

        class PORT(Module):
            def __init__(self, aw, dw):
                self.adr = Signal(aw)
                self.dat_r = Signal(dw)

                self.sync += self.dat_r.eq(self.adr)

        self.submodules.port = PORT(bits_for(1024), 8)

            
        def _deferred_src_gen():
            yield
            yield from self.src_gen

        def _deferred_sink_gen():
            yield
            yield from self.sink_gen

        class SimSource(SimActor):
            def __init__(self):
                self.source = Endpoint(dmatpl(1024))
                SimActor.__init__(self, _deferred_src_gen())

        class SimSink(SimActor):
            def __init__(self):
                self.sink = Endpoint(D_LAST)
                SimActor.__init__(self, _deferred_sink_gen())

        self.submodules.src = SimSource()
        self.submodules.c = Consumer(self.port, 1024)
        self.comb += self.src.source.connect(self.c.sink)
        self.comb += self.src.busy.eq(0)

        self.submodules.dmp = SimSink()
        self.comb += self.c.source.connect(self.dmp.sink)
        self.comb += self.dmp.busy.eq(0)

    def setSeq(self, src_gen, sink_gen):
        self.src_gen = src_gen
        self.sink_gen = sink_gen

    def do_simulation(self, s):
        pass


class TestConsumer(unittest.TestCase):
    def setUp(self):
        self.tb = TestBench()
        self.sim = Simulator(self.tb)

    def _run(self):
        with self.sim:
            self.sim.run(200)

    def testConsumer2(self):
        tests = [
            {"start":0,   "count":  4},
            {"start":555, "count": 77}
        ]

        def srcgen():
            for t in tests:
                yield Token('source', t)
                yield

        def sinkgen():
            for test in tests:
                for n, ck in enumerate(range(
                    test["start"], test["start"] + test["count"])):
                    last = n == test["count"] - 1

                    t = Token("sink", idle_wait=True)
                    yield t
                    
                    self.assertEqual(t.value['d'], ck & 0xFF)
                    self.assertEqual(t.value['last'], last)
                    self.last = t.value

        self.tb.setSeq(srcgen(), sinkgen())

        self._run()

        self.assertEqual(self.last, {"d":119, "last":1})

if __name__ == "__main__":
    unittest.main()
