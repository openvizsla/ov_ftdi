from migen.fhdl.std import *
from migen.fhdl.bitcontainer import bits_for

def dmatpl(depth):
    b = bits_for(depth-1)
    return [('start', b), ('count', b)]

class Acc(Module):
    def __init__(self, *args, **kwargs):
        self.v = Signal(*args, **kwargs)

        self._n = Signal(*args, **kwargs)
        self._s = Signal(1)

        self.sync += If(self._s, self.v.eq(self._n))

    def set(self, val):
        return self._n.eq(val), self._s.eq(1)

class Acc_inc(Acc):
    def inc(self):
        return self._n.eq(self.v+1), self._s.eq(1)

class Acc_inc_sat(Acc):
    def inc(self):
        return If(self.v != (1<<flen(self.v))-1, self._n.eq(self.v+1), self._s.eq(1))

class Acc_or(Acc):
    def _or(self, v):
        return self._n.eq(self.v | v), self._s.eq(1)

