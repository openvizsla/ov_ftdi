`timescale 1ns / 1ps

module led(
    inout [1:0] M,
    inout [7:0] D,
    input BUSY_DOUT,
    output CSI_B,
    input CCLK,
    input ACBUS0,
	 input RDWR_B,
	 output ACBUS2,
	 output ACBUS3,
	 input INIT_B,
	 input CLKOUT,
	 output ACBUS6,
	 
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
	wire clk_sdram, LOCKED;

	cs_icon i_cs_icon (
		.CONTROL0(CONTROL0) // INOUT BUS [35:0]
	);

	cs_ila i_cs_ila (
		.CONTROL(CONTROL0), // INOUT BUS [35:0]
		.CLK(ULPI_CLK), // IN
		.TRIG0({S2, DEBUG[62:0]}) // IN BUS [63:0]
	);

//	assign led1=~fifo_empty;
//	assign led2=~fifo_full;
//	assign led3=rst;
	//assign led1 = CLKOUT;
	//assign led2 = rst;
	//assign led3 = CCLK;
	
	// Implicit reset for the first 2^24 cycles.

	reg [25:0] reset_counter = 0;

	always @(posedge clk_sdram)
	begin
		if (!SW1)
			reset_counter <= 0;
		else if (!reset_counter[25])
			reset_counter <= reset_counter + 1'b1;
	end

	wire rst;
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
		 .DATA_CLK(clk_sdram), 
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
		.CLK(clk_sdram), 
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
	wire fifo_empty;
	wire fifo_full;
	wire read12;
	wire write12;
	wire wr;
	assign wr = 1'b1;

	reg [7:0] data;

	always @(posedge CLKOUT)
	begin
			data <= data + 1'b1;
	end
//	reg [7:0] data = 8'h42;
   usbstreamer streamer (
	   .mclk(CLKOUT),
		.reset(~rst),
		.usb_d(D),
		.usb_rxf_n(ACBUS0),
		.usb_txe_n(CCLK),
		.usb_rd_n(ACBUS2),
		.usb_wr_n(ACBUS3),
		.usb_oe_n(ACBUS6),
		.have_space(have_space),
		.data(data),
		.wr(wr),
		.fifo_full(fifo_full),
		.fifo_empty(fifo_empty),
		.read12(read12),
		.write12(write12)
	);
	
	//
	// sdram test
	//


	wire clk_sdram_90;

  clkgen i_clkgen
   (
    .CLK_IN1(CLK),
    .CLKOUT(clk_sdram),
	 //.CLKOUT90(clk_sdram_90),
    .LOCKED(LOCKED)
	 );

	assign clk_sdram_90 = clk_sdram;

	ODDR2 buf_vclk1 (
			  .Q(SD_CLK),
			  .C0(clk_sdram_90),
			  .C1(~clk_sdram_90),
			  .CE(1'b1),
			  .D0(1'b0),
			  .D1(1'b1),
			  .R(1'b0),
			  .S(1'b0)
	);

	// memory interface - write request
	wire user_wreq;
	wire user_wstart;
	wire user_wdone;
	wire [23:0] user_waddr;
	wire [9:0] user_wsize;
	wire user_wen;
	wire [15:0] user_wdata;

	// memory interface - read request
	wire user_rreq;
	wire user_rstart;
	wire user_rdone;
	wire [23:0] user_raddr;
	wire [9:0] user_rsize;
	wire user_rvalid;
	wire [15:0] user_rdata;

	// reset
	wire status;
	wire err_strobe;
	wire err_latch;

	mt_extram_sdrctrl mt_extram_sdrctrl_inst (
			  .clk(clk_sdram),
			  .rst(rst),
			  .user_wreq(user_wreq),
			  .user_wstart(user_wstart),
			  .user_wdone(user_wdone),
			  .user_waddr(user_waddr),
			  .user_wsize(user_wsize),
			  .user_wen(user_wen),
			  .user_wdata(user_wdata),
			  .user_rreq(user_rreq),
			  .user_rstart(user_rstart),
			  .user_rdone(user_rdone),
			  .user_raddr(user_raddr),
			  .user_rsize(user_rsize),
			  .user_rvalid(user_rvalid),
			  .user_rdata(user_rdata),
			  .SD_CKE(SD_CKE),
			  .SD_CS(SD_CS),
			  .SD_WE(SD_WE),
			  .SD_CAS(SD_CAS),
			  .SD_RAS(SD_RAS),
			  .SD_DQM(SD_DQM),
			  .SD_BA(SD_BA),
			  .SD_A(SD_A),
			  .SD_DQ(SD_DQ)
	);

	mt_extram_test mt_extram_test_inst (
			  .clk(clk_sdram),
			  .rst(rst),
			  .user_wreq(user_wreq),
			  .user_wstart(user_wstart),
			  .user_wdone(user_wdone),
			  .user_waddr(user_waddr),
			  .user_wsize(user_wsize),
			  .user_wen(user_wen),
			  .user_wdata(user_wdata),
			  .user_rreq(user_rreq),
			  .user_rstart(user_rstart),
			  .user_rdone(user_rdone),
			  .user_raddr(user_raddr),
			  .user_rsize(user_rsize),
			  .user_rvalid(user_rvalid),
			  .user_rdata(user_rdata),
			  .status(status),
			  .err_strobe(err_strobe),
			  .err_latch(err_latch)
	);
	
	assign led1 = ~status;
	assign led2 = ~err_strobe;
	assign led3 = ~err_latch;

endmodule
