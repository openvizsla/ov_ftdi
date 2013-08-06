`timescale 1ns / 1ps

//
// ULPI sniffer
//
// The ULPI sniffer has two ends:
// One, clocked with the ULPI CLK, and another one clocked with the host clock.
//
// Reading/writing registers: (Synchronous to ULPI_CLK)
// - drive REG_ADDR (and REG_DATA_WRITE for writing)
// - assert REG_WRITE_REQ/REG_READ_REQ.
// - wait until REG_WRITE_ACK/REG_READ_ACK is asserted.
// - de-assert REG_WRITE_REQ/REG_READ_REQ.
// REG_ADDR and REG_DATA_WRITE may not be changed once REQ is asserted!
// REQ may not be de-asserted without ACK being asserted first!
//
// Receiving data: (Synchronous to DATA_CLK) 
// - assert READY to receive data (in the next cycle)
// - if VALID is asserted, data is available on {RXCMD, DATA}
//

module ulpi(
		// ULPI
    output ULPI_RST,
    input ULPI_NXT,
    input ULPI_CLK,
    input ULPI_DIR,
    output ULPI_STP,
    inout [7:0] ULPI_D,
	 output [63:0] DEBUG,

	 input RST,

    input [5:0] REG_ADDR,
    input [7:0] REG_DATA_WRITE,
    output [7:0] REG_DATA_READ,
    input REG_WRITE_REQ,
    output REG_WRITE_ACK,
    input REG_READ_REQ,
    output REG_READ_ACK,

		// DATA
    input DATA_CLK,
    output RXCMD,
    output [7:0] DATA,
    output VALID,
	 input READY
    );

// -----------------------------------------------------------

parameter IDLE  = 11'b00000000001; // IDLE state (or turn-around to RX)
parameter RX    = 11'b00000000010; // DIR=1 without register read (or turn-around after RX)
parameter RW0   = 11'b00000000100; // RegWrite on the bus, NXT=0
parameter RW1   = 11'b00000001000; // RegWrite on the bus, NXT=1
parameter RWD   = 11'b00000010000; // register data on the bus (driven by FPGA)
parameter RWS   = 11'b00000100000; // STP=1
parameter RR0   = 11'b00001000000; // RegRead on the bus, NXT=0
parameter RR1   = 11'b00010000000; // RegRead on the bus, NXT=1
parameter TA2   = 11'b00100000000; // Turnaround before register read
parameter RRD   = 11'b01000000000; // register data on the bus (driven by ULPI)
parameter ERROR = 11'b10000000000; // invalid state (should never happen)

//
// The state for the next cycle (combinatorial based on ulpi_state, ULPI_DIR and ULPI_NXT).
//

wire [10:0] ulpi_state_next;

//
// The state for this cycle.
//

reg [10:0] ulpi_state;

//
// What we want to drive for the next cycle (combinatorial; even though it's a reg).
//

reg [7:0] ulpi_data_next;
reg ulpi_data_tristate_next;
reg ulpi_stp_next;

// [outdated]
// The lower nibble is clocked out first (on the rising edge),
// the upper nibble is clocked out last (on the falling edge).
// Because ulpi_data_next is combinatorial, it'll change
// after the rising edge. 
// ODDR2 will capture the lower nibble on the rising edge (so that's fine),
// but it will capture the upper nibble at the falling edge - 
// so ulpi_data_next isn't valid data for this cycle anymore.
// So register ulpi_data_upper at the rising edge.
//
// Similarly, ulpi_data_tristate and ulpi_stp need to be registered.
//

reg [7:0] ulpi_data_out;
reg ulpi_data_tristate;
reg ulpi_stp;

//
// Register read/write interface.
// RegWriteReq is high when there is an outstanding/unacknowledged
// write request. Same for RegReadReq.
// For register reads, the last read value will be buffered in 
// ulpi_data_read.
//

reg RegWriteAck, RegReadAck;

wire RegWriteReq = RegWriteReqR && !RegWriteAck;
wire RegReadReq = RegReadReqR && !RegReadAck;

assign REG_WRITE_ACK = RegWriteAck;
assign REG_READ_ACK = RegReadAck;

reg [7:0] ulpi_data_read;

//
// In "RX" state, ULPI_NXT indicates if the current ULPI_D 
// belongs to a usb packet or is an RXCMD.
// Because the complete ULPI_D is only available at the rising edge
// (to the next cycle), we can only process it one cycle after that.
// ulpi_nxt_l delays ULPI_NXT by one cycle.
//

reg ulpi_nxt_l;

//
// All data received (RXCMDs and PKT data) will be passed to the FIFO.
// (That means, all data during "RX" cycles where DIR=1).
// fifo_wen is the write enable for the (delayed and demuxed) ULPI_D.
//

reg fifo_wen;

//
// Data capture/demux.  [outdated]
// ulpi_data_rising and ulpi_data_falling are the nibbles captured
// at the individual clock edges. Note that ULPI_D is delayed so that 
// the falling edge will actually be used to capture the first (lower),
// and the second (rising) edge will be used to capture the second (upper)
// nibble. That means that the falling nibble of the previous cycle
// and the rising nibble of the current cycle will belong to the 8-bit
// data of the last cycle.
// That means that the falling edge nibble needs to be registered to form
// a byte together with the rising edge nibble (that is thus already 
// registered at the rising edge).
//

wire [7:0] ulpi_data_in;

assign ulpi_data_in = ULPI_D;

assign ULPI_D = ulpi_data_tristate ? 8'bZ : ulpi_data_out;

//
// Construct the data that's written to the FIFO.
// It's one bit of "RXCMD-or-DATA" indicator plus 8 bits of data.
//

wire [8:0] fifo_din;
wire [8:0] fifo_dout;
assign fifo_din = {~ulpi_nxt_l, ulpi_data_in};

//
// Debug bus.
//

assign DEBUG = {fifo_din, fifo_wen,  REG_ADDR, ulpi_data_read, ULPI_DIR, ULPI_NXT, ULPI_STP, RegReadAck, RegReadReq, ULPI_CLK, ULPI_D, RST, 2'b00, ulpi_state, ulpi_data_in};

//
// ULPI state machine. 
// Most of the states allow an abort to move to the RX state, other
// than that it's straight forward.
//
	
assign ulpi_state_next = ulpi_fsm(ulpi_state, ULPI_DIR, ULPI_NXT);

function [10:0] ulpi_fsm;
	input [10:0] ulpi_state;
	input ULPI_DIR;
	input ULPI_NXT;

	case (ulpi_state)
		IDLE:
			ulpi_fsm = (!ULPI_DIR && !ULPI_NXT && !(RegWriteReq || RegReadReq)) ? IDLE :
				(ULPI_DIR && !ULPI_NXT) ? RX :
				(ULPI_DIR && ULPI_NXT) ? RX : // TODO: When exactly does this happen?
				(RegWriteReq) ? RW0 :
				(RegReadReq) ? RR0 :
				ERROR;
		RX:
			ulpi_fsm = (ULPI_DIR) ? RX : IDLE;
		RW0:
			ulpi_fsm = (!ULPI_DIR && !ULPI_NXT) ? RW1 :
				(ULPI_DIR && !ULPI_NXT) ? RX :
				ERROR;
		RW1:
			ulpi_fsm = (!ULPI_DIR && !ULPI_NXT) ? RW1 :
				(ULPI_DIR && !ULPI_NXT) ? RX :
				(!ULPI_DIR && ULPI_NXT) ? RWD :
				ERROR;
		RWD:
			ulpi_fsm = (ULPI_DIR && !ULPI_NXT) ? RX :
				(!ULPI_DIR && ULPI_NXT) ? RWS :
				ERROR;
		RWS:
			ulpi_fsm = (!ULPI_DIR && !ULPI_NXT) ? IDLE :
				(ULPI_DIR && ULPI_NXT) ? RX :
				ERROR;
		RR0:
			ulpi_fsm = (!ULPI_DIR && !ULPI_NXT) ? RR1 :
				(ULPI_DIR && !ULPI_NXT) ? RX :
				ERROR;
		RR1:
			ulpi_fsm = (!ULPI_DIR && !ULPI_NXT) ? RR1 :
				(!ULPI_DIR && ULPI_NXT) ? TA2 :
				(ULPI_DIR && !ULPI_NXT) ? RX :
				ERROR;
		TA2:
			ulpi_fsm = (ULPI_DIR && ULPI_NXT) ? RX :
				(ULPI_DIR && !ULPI_NXT) ? RRD :
				ERROR;
		RRD:
			ulpi_fsm = (!ULPI_DIR && !ULPI_NXT) ? IDLE :
				(ULPI_DIR && !ULPI_NXT) ? RX :
				ERROR;
		ERROR:
			ulpi_fsm = IDLE;
		default:
			ulpi_fsm = IDLE;
	endcase
endfunction

//
// State sequential logic and register read/write ack generation.
//

reg RegWriteReqR, RegReadReqR;

always @(posedge ULPI_CLK)
begin
	if (RST == 1) begin
		ulpi_state <= IDLE;
	end else begin
		ulpi_state <= ulpi_state_next;
		
		RegReadReqR <= REG_READ_REQ;

		if (!RegReadReqR)
			RegReadAck <= 0;
		else if (ulpi_state == RRD)
			RegReadAck <= 1;
		
		RegWriteReqR <= REG_WRITE_REQ;
		
		if (!RegWriteReqR)
			RegWriteAck <= 0;
		else if (ulpi_state == RWD)
			RegWriteAck <= 1;
	end
end

//
// Prepare outputs; looking ahead at the next state.
// This is purely combinatorial.
//

always @(*)
begin
	case (ulpi_state_next)
		IDLE:
		begin
			ulpi_data_next = 8'h00; // IDLE
			ulpi_data_tristate_next = 0;
			ulpi_stp_next = 0;
		end
		RX:
		begin
			ulpi_data_next = 8'h00;
			ulpi_data_tristate_next = 1;
			ulpi_stp_next = 0;
		end
		RW0:
		begin
			ulpi_data_next = {2'b10, REG_ADDR[5:0]}; // REGW
			ulpi_data_tristate_next = 0;
			ulpi_stp_next = 0;
		end
		RW1:
		begin
			ulpi_data_next = {2'b10, REG_ADDR[5:0]}; // REGW
			ulpi_data_tristate_next = 0;
			ulpi_stp_next = 0;
		end
		RWD:
		begin
			ulpi_data_next = REG_DATA_WRITE;
			ulpi_data_tristate_next = 0;
			ulpi_stp_next = 0;
		end
		RWS:
		begin
			ulpi_data_next = 8'h00; // IDLE
			ulpi_data_tristate_next = 0;
			ulpi_stp_next = 1;
		end
		RR0:
		begin
			ulpi_data_next = {2'b11, REG_ADDR[5:0]}; // REGR
			ulpi_data_tristate_next = 0;
			ulpi_stp_next = 0;
		end
		RR1:
		begin
			ulpi_data_next = {2'b11, REG_ADDR[5:0]}; // REGR
			ulpi_data_tristate_next = 0;
			ulpi_stp_next = 0;
		end
		TA2:
		begin
			ulpi_data_next = 8'h00;
			ulpi_data_tristate_next = 1;
			ulpi_stp_next = 0;
		end
		RRD:
		begin
			ulpi_data_next = 8'h00;
			ulpi_data_tristate_next = 1;
			ulpi_stp_next = 0;
		end
		ERROR:
		begin
			ulpi_data_next = 8'h00;
			ulpi_data_tristate_next = 1;
			ulpi_stp_next = 0;
		end
		default:
		begin
			ulpi_data_next = 8'h00;
			ulpi_data_tristate_next = 1;
			ulpi_stp_next = 0;
		end
	endcase
end

//
// drive outputs. The data to output was already determined,
// but gets registered here.
//

assign ULPI_STP = ulpi_stp | RST;

always @(posedge ULPI_CLK)
begin
	ulpi_stp <= ulpi_stp_next;
	ulpi_data_out <= ulpi_data_next;
	ulpi_data_tristate <= ulpi_data_tristate_next;
end

//
// If the current state is RX, then at the end of the cycle, fifo_din
// will be filled and can be captured (together with ulpi_nxt_l) 
// in the next cycle.
//

reg was_RRD;

always @(posedge ULPI_CLK) begin
	ulpi_nxt_l <= ULPI_NXT;
	
	fifo_wen <= (ulpi_state == RX && ULPI_DIR) ? 1'b1 : 1'b0;
	
	was_RRD <= ulpi_state == RRD;
	if (was_RRD)
		ulpi_data_read <= ulpi_data_in;
end

//
// construct 9-bit data
//

fifo fifo (
  .rst(RST),
  .wr_clk(ULPI_CLK),
  .rd_clk(DATA_CLK),
  .din(fifo_din),
  .wr_en(fifo_wen),
  .rd_en(READY),
  .dout(fifo_dout),
  .valid(valid),
  .full(),
  .empty()
);

assign ULPI_RST = ~RST; // low active reset

assign RXCMD = fifo_dout[8];
assign DATA = fifo_dout[7:0];
assign VALID = valid;

endmodule
