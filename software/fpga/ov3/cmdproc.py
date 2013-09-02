from bus_interleave import BusDecode, BusEncode, BusInterleave
from csr_master import CSR_Master

from migen.fhdl.std import *
from ftdi_bus import FTDI_sync245

from migen.genlib.cdc import NoRetiming, MultiReg

from migen.flow.network import DataFlowGraph, CompositeActor
from migen.flow.actor import Source

from migen.bus.csr import Interconnect
from migen.bank.csrgen import BankArray


# CmdProc (perhaps misnamed) handles command parsing on the ftdi interface
# inserting cmd responses, and multiplexing the cmd responses with the streaming data
class CmdProc(Module):
    def __init__(self, ftdi_sync, streaming_source):

        # CSR Command Decoding
        bdec = BusDecode()
        self.comb += [
                bdec.sink.stb.eq(ftdi_sync.incoming_fifo.readable),
                bdec.sink.payload.d.eq(ftdi_sync.incoming_fifo.dout),
                ftdi_sync.incoming_fifo.re.eq(bdec.sink.ack),
                
                ]
        
        # Bus master
        busmaster = CSR_Master(has_completion=True)
        self.master = busmaster.master

        # Encode output for response
        benc = BusEncode()
        
        # Connect decoder to busmaster to encoder
        g = DataFlowGraph()
        g.add_connection(bdec, busmaster)
        g.add_connection(busmaster, benc)
        self.submodules.fg = CompositeActor(g)

        # Bus interleaver to merge streaming and response packets
        bilv = BusInterleave([benc, streaming_source])
        self.submodules += bilv
        self.comb += [
                ftdi_sync.output_fifo.we.eq(bilv.source.stb),
                ftdi_sync.output_fifo.din.eq(bilv.source.payload.d),
                bilv.source.ack.eq(ftdi_sync.output_fifo.writable)
                ]



