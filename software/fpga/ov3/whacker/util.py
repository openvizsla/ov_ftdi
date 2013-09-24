from migen.fhdl.std import *
from migen.fhdl.size import bits_for
from ulpi import ULPI_DATA

def dmatpl(depth):
    b = bits_for(depth-1)
    return [('start', b), ('count', b)]

class Acc(Module):
    def __init__(self, *args, **kwargs):
        self.v = Signal(*args, **kwargs)
        self.n = Signal(*args, **kwargs)

        self.comb += self.n.eq(self.v)
        self.sync += self.v.eq(self.n)

    def set(self, val):
        return self.n.eq(val)

class Acc_inc(Acc):
    def inc(self):
        return self.n.eq(self.v+1)

class Acc_or(Acc):
    def _or(self, v):
        return self.n.eq(self.v | v)

