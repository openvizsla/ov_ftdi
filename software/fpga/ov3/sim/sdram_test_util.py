from migen.fhdl.std import *
from ovhw.sdramctl import SDRAMCTL
import ovplatform.sdram_params
import migen.test.support
from sim.util import par, gather_files
import os.path
from migen.sim import icarus
from migen.sim.generic import Simulator, TopLevel

class SDRAMModel(Module):
    def __init__(self, chipname, nchips=1):

        smp = ovplatform.sdram_params.getSDRAMModelParams(chipname, nchips)

        self.extra_files = [smp.filename]

        _p = self.params = smp.params

        self.dq = Signal(_p.databits)
        # TODO - check addr bits calculation when colbits > rowbits
        self.a = Signal(_p.rowbits)
        self.ba = Signal(_p.bankbits)
        self.dqm = Signal(_p.databits//8)
        self.cke = Signal()
        self.cs_n = Signal()
        self.ras_n = Signal()
        self.cas_n = Signal()
        self.we_n = Signal()
        self.clk = Signal()

        chip_width = _p.databits // nchips

        for i in range(nchips):
            dq_slice = self.dq[i * chip_width:(i + 1) * chip_width]
            self.specials.pll = Instance(
                smp.modelname,
                Instance.InOut("Dq", dq_slice),
                Instance.Input("Addr", self.a),
                Instance.Input("Ba", self.ba),
                Instance.Input("Clk", self.clk),
                Instance.Input("Cke", self.cke),
                Instance.Input("Cs_n", self.cs_n),
                Instance.Input("Ras_n", self.ras_n),
                Instance.Input("Cas_n", self.cas_n),
                Instance.Input("We_n", self.we_n),
                Instance.Input("Dqm", self.dqm)
            )


class TestSDRAMComplex(Module):
    def __init__(self, sdram_modname):
        self.submodules.sdram = SDRAMModel(sdram_modname)
        inv = Signal()
        self.comb += inv.eq(~ClockSignal())

        # SDRAM intrinsic parameters
        _p = self.sdram.params

        self.submodules.sdctl = SDRAMCTL(
            self.sdram,
            inv, inv,
            **_p._asdict()
        )

        self.hostif = self.sdctl.hostif


class TestMaster(Module):
    def __init__(self, hostif, stop_on_finish=True):
        self.hostif = hostif
        self.stop_on_finish=stop_on_finish
        self.complete = False

    def setSeq(self, gen):
        self.geninst = gen

    def __issue(self, addr, wr):
        # Issue the command and wait for ack
        self.p.hostif.i_wr = wr
        self.p.hostif.i_addr = addr
        self.p.hostif.i_stb = 1

        yield
        while not self.p.hostif.i_ack: yield

        self.p.hostif.i_stb = 0

    # Data pipe - wait for the controller to strobe
    def __d_step(self):
        yield
        while (not self.p.hostif.d_stb):
            yield

    # Data pipe - send and wait for a termination cycle
    def __d_term(self):
        self.p.hostif.d_term = 1
        yield from self.__d_step()
        self.p.hostif.d_term = 0
    
    # Data pipe - handle a write stream
    def __d_write(self, buf):
        self.p.hostif.d_term = 0

        for val in buf:
            self.p.hostif.d_write = val
            yield from self.__d_step()

        yield from self.__d_term()

    # Data pipe - handle a read stream
    def __d_read(self, ct):
        self.p.hostif.d_term = 0

        buf = []
        for n in range(ct):
            yield from self.__d_step()
            buf.append(self.p.hostif.d_read)

        yield from self.__d_term()

        return buf

    def write_txn(self, addr, buf):
        assert len(buf) > 0

        yield from par(
            self.__issue(addr, 1),
            self.__d_write(buf)
        )

    def read_txn(self, addr, ct):
        hostif = self.hostif
        buf = yield from par(
            self.__issue(addr, 0),
            self.__d_read(ct)
        )
        return buf[1]

    def do_simulation(self, selfp):
        self.p = selfp
        if self.geninst:
            try:
                next(self.geninst)
            except StopIteration:
                self.geninst = None
                self.complete = True
                if self.stop_on_finish:
                    raise StopSimulation
        else:
            self.complete = True


def mgen(x):
    """Defers the master parameter until bound to a master"""
    def _a(self, *args):
        def _b(master):
            return x(self, master, *args)
        return _b
    return _a

class SDRAMTestSequences:
    """Transaction sequences useful in testing the SDRAM controller"""
    @mgen
    def _rw(self, master, s, l):
        yield from master.write_txn(s, range(s, s+l))
        res = yield from master.read_txn(s, l)

        self.assertEqual(res, list(range(s, s+l)))

    @mgen
    def _overlap(self, master, s, l):
        yield from master.write_txn(s, [0xCAFE] * l)
        yield from master.write_txn(s + 1, range(s+1, s + l - 1) )
        res = yield from master.read_txn(s, l)

        self.assertEqual(res, 
            [0xCAFE] + list(range(s+1, s+l-1)) + [0xCAFE])

    @mgen
    def _b2b_read(self, master, s, l):
        yield from master.write_txn(s, range(l))
        res1 = yield from master.read_txn(s, l//2)
        res2 = yield from master.read_txn(s+l//2, l//2)

        self.assertEqual(res1, list(range(l//2)))
        self.assertEqual(res2, list(range(l//2,l)))

    @mgen
    def _wait(self, master, n):
        for i in range(0, n):
            yield

class FileNotFoundError(Exception):
    pass

class SDRAMUTFramework:
    def _inner_setup(self):
        # Verify that all necessary files are present
        files = gather_files(self.tb)
        for i in files:
            if not os.path.exists(i):
                raise FileNotFoundError("Please download and save the vendor "
                                        "SDRAM model in %s (not redistributable)"
                                        % i)

        runner = icarus.Runner(extra_files=files, keep_files= True)
        #vcd = "test_%s.vcd" % self.__class__.__name__
        vcd = None
        self.sim = Simulator(self.tb, TopLevel(None), sim_runner=runner) 
