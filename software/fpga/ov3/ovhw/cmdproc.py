from migen import *

from ovhw.bus_interleave import BusDecode, BusEncode, BusInterleave
from ovhw.csr_master import CSR_Master

# CmdProc (perhaps misnamed) handles command parsing on the ftdi interface
# inserting cmd responses, and multiplexing the cmd responses with the streaming data
class CmdProc(Module):
    def __init__(self, ftdi_sync, streaming_sources):

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
        #g = DataFlowGraph()

        pipeline = [bdec, busmaster, benc]
        for s, d in zip(pipeline[:-1], pipeline[1:]):
            self.comb += s.source.connect(d.sink)

        # Bus interleaver to merge streaming and response packets
        bilv = BusInterleave([benc] + streaming_sources)
        self.submodules += bilv
        self.comb += [
                ftdi_sync.output_fifo.we.eq(bilv.source.stb),
                ftdi_sync.output_fifo.din.eq(bilv.source.payload.d),
                bilv.source.ack.eq(ftdi_sync.output_fifo.writable)
                ]



