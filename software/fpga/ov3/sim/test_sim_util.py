import sim.util
import unittest

class TestPar(unittest.TestCase):
    def test_par_run(self):
        def gen_a():
            yield 1
            yield 2
            return 'A'
        def gen_b():
            yield 1
            yield 2
            return 'B'

        def gen_c():
            v = yield from sim.util.par(gen_a(), gen_b())
            return v

        value = None
        self.assertEqual(sim.util.run(gen_c()), ('A', 'B'))
