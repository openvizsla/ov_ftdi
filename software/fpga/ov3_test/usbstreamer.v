/*  norsniff.v - NOR sniffer for PS3

Copyright (C) 2010-2011  Hector Martin "marcan" <hector@marcansoft.com>

This code is licensed to you under the terms of the GNU GPL, version 2;
see file COPYING or http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt
*/

module usbstreamer (
	input mclk, reset,
	inout [7:0] usb_d, input usb_rxf_n, usb_txe_n, output usb_rd_n, output reg usb_wr_n, output usb_oe_n,
	output have_space, input [7:0] data, input wr, output fifo_full, output fifo_empty, output read12, output write12
);

	// unused read lines
	assign usb_rd_n = 1;
	assign usb_oe_n = 1;

	// FIFO configuration
	parameter FIFO_THRESHOLD = 8;
	parameter FIFO_LOG_SIZE = 13;
	parameter FIFO_SIZE = 2**FIFO_LOG_SIZE;

	// FIFO and pointers
	reg [7:0] fifo_mem[FIFO_SIZE-1:0];

	reg [FIFO_LOG_SIZE-1:0] fifo_read_ptr;
	reg [FIFO_LOG_SIZE-1:0] fifo_write_ptr;
	assign read12 = fifo_read_ptr[12];
	assign write12 = fifo_write_ptr[12];
	wire [FIFO_LOG_SIZE-1:0] fifo_write_ptr_next = fifo_write_ptr + 1;
	wire [FIFO_LOG_SIZE-1:0] fifo_used_space = fifo_write_ptr - fifo_read_ptr;

	assign fifo_empty = fifo_write_ptr == fifo_read_ptr;
	assign fifo_full = fifo_write_ptr_next == fifo_read_ptr;
	assign have_space = fifo_used_space < (FIFO_SIZE - FIFO_THRESHOLD);

	// silly FT2232 handshake handking
	reg just_sent;
	reg pending_byte;

	// data output buffer
	reg [7:0] usb_dout;

	// we're only doing writes so no Z state
	assign usb_d = usb_dout;

	// FIFO write process
	always @(posedge mclk or negedge reset) begin
		if (!reset) begin
			fifo_write_ptr <= 0;
		end else begin
			if (!fifo_full && wr) begin
				fifo_mem[fifo_write_ptr] <= data;
				fifo_write_ptr <= fifo_write_ptr + 1'b1;
			end
		end
	end

	// FIFO read / USB stream process
	always @(posedge mclk or negedge reset) begin
		if (!reset) begin
			fifo_read_ptr <= 0;
			usb_wr_n <= 1;
			just_sent <= 0;
			pending_byte <= 0;
			// note: no reset of usb_dout because it's really a BRAM output port which is only synchronous
		end else begin
			// send a byte if the FT2232 lets us, and we have stuff in the FIFO _or_ a pending byte that it barfed back at us previously
			if ((!fifo_empty || pending_byte) && !usb_txe_n) begin
				// only fetch new byte if we don't have a byte hanging around
				if (!pending_byte) begin
					usb_dout <= fifo_mem[fifo_read_ptr];
					fifo_read_ptr <= fifo_read_ptr + 1'b1;
				end
				usb_wr_n <= 0;
				just_sent <= 1;
				pending_byte <= 0;
			end else begin
				// if we sent a byte and the FT2232 rejected it, hold it
				if (just_sent && usb_txe_n)
					pending_byte <= 1;
				// and keep usb_dout state for next try
				usb_wr_n <= 1;
				just_sent <= 0;
			end
		end
	end
endmodule

