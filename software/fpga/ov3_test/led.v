`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    13:39:56 07/25/2013 
// Design Name: 
// Module Name:    led 
// Project Name: 
// Target Devices: 
// Tool versions: 
// Description: 
//
// Dependencies: 
//
// Revision: 
// Revision 0.01 - File Created
// Additional Comments: 
//
//////////////////////////////////////////////////////////////////////////////////
module led(
    inout [1:0] M,
    inout [7:0] D,
    input BUSY_DOUT,
    output CSI_B,
    output CCLK,
    output ACBUS0,
	 input RDWR_B,
	 input ACBUS2,
	 input ACBUS3,
	 input INIT_B,
	 input ACBUS6,
	 
    inout [7:0] ULPI_D,
    input ULPI_DIR,
    input ULPI_CLK,
    output ULPI_STP,
    input ULPI_NXT,
    output ULPI_RST,
 
    output [12:0] SD_A,
    inout [15:0] SD_DQ,
    output SD_WE,
    output SD_CLK,
	 output SD_CKE,
    output SD_CAS,
    output [1:0] SD_DQM,
    output SD_RAS,
    output SD_CS,
    output [1:0] SD_BA,
    output led1,
	 output led2,
	 output led3,
	 input CLK,
	 input SW1,
	 
	 input S2);

wire [35:0] CONTROL0;
wire [63:0] DEBUG;

cs_icon i_cs_icon (
    .CONTROL0(CONTROL0) // INOUT BUS [35:0]
);

cs_ila i_cs_ila (
    .CONTROL(CONTROL0), // INOUT BUS [35:0]
    .CLK(ULPI_CLK), // IN
    .TRIG0({S2, DEBUG[62:0]}) // IN BUS [63:0]
);

assign led1=~rst;
assign led2=1'b1;
assign led3=rst;

//
	// Implicit reset for the first 2^24 cycles.
	//

	reg [25:0] reset_counter = 0;

	always @(posedge CLK)
	begin
		if (!SW1)
			reset_counter <= 0;
		else if (!reset_counter[25])
			reset_counter <= reset_counter + 1'b1;
	end

	assign rst = ~reset_counter[25]; // start with a reset
	
	wire [5:0] reg_address;
	wire [7:0] reg_data_write;
	wire [7:0] reg_data_read;
	wire reg_write_req, reg_write_ack, reg_read_req, reg_read_ack;
	
	wire [7:0] ulpi_data;
	wire ulpi_rxcmd;
	wire ulpi_ready;
	
	ulpi ulpi_inst (
		 .ULPI_RST(ULPI_RST), 
		 .ULPI_NXT(ULPI_NXT), 
		 .ULPI_CLK(ULPI_CLK), 
		 .ULPI_DIR(ULPI_DIR), 
		 .ULPI_STP(ULPI_STP), 
		 .ULPI_D(ULPI_D), 
		 .DEBUG(DEBUG),
		 .DATA_CLK(CLK), 
		 .RST(rst), 
		 .REG_ADDR(reg_address), 
		 .REG_DATA_WRITE(reg_data_write), 
		 .REG_DATA_READ(reg_data_read), 
		 .REG_WRITE_REQ(reg_write_req), 
		 .REG_WRITE_ACK(reg_write_ack), 
		 .REG_READ_REQ(reg_read_req), 
		 .REG_READ_ACK(reg_read_ack), 
		 .RXCMD(ulpi_rxcmd), 
		 .DATA(ulpi_data), 
		 .VALID(ulpi_valid),
		 .READY(1'b1) // !xmos_full)
		 );

	ulpi_ctrl ulpi_ctrl_inst (
		.CLK(CLK), 
		.REG_ADDR(reg_address), 
		.REG_DATA_WRITE(reg_data_write), 
		.REG_DATA_READ(reg_data_read), 
		.REG_WRITE_REQ(reg_write_req), 
		.REG_WRITE_ACK(reg_write_ack), 
		.REG_READ_REQ(reg_read_req), 
		.REG_READ_ACK(reg_read_ack), 
		.RST(rst)
		);

wire have_space;
reg [7:0] data = 8'h42;
assign wr = 1'b1;

   usbstreamer streamer (
	   .mclk(CLK),
		.reset(rst),
		.usb_d(D),
		.usb_rxf_n(ACBUS0),
		.usb_txe_n(CCLK),
		.usb_rd_n(ACBUS2),
		.usb_wr_n(ACBUS3),
		.usb_oe_n(ACBUS6),
		.have_space(have_space),
		.data(data),
		.wr(wr)
		);
endmodule
