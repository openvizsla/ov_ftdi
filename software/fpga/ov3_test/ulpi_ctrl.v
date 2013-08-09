`timescale 1ns / 1ps
module ulpi_ctrl(
    input CLK,
    output [5:0] REG_ADDR,
    output [7:0] REG_DATA_WRITE,
    input [7:0] REG_DATA_READ,
    output REG_WRITE_REQ,
    input REG_WRITE_ACK,
    output REG_READ_REQ,
    input REG_READ_ACK,
    input RST
    );

	reg [1:0] cnt;
	reg [5:0] cnt2;

	reg ulpi_initialized;
	reg reg_write_req, reg_read_req;
	wire reg_write_ack, reg_read_ack;
	reg [7:0] reg_data_write;
	wire [7:0] reg_data_read;
	reg [5:0] reg_address;
	
	assign REG_ADDR = reg_address;
	assign REG_DATA_WRITE = reg_data_write;
	assign reg_data_read = REG_DATA_READ;
	assign REG_WRITE_REQ = reg_write_req;
	assign reg_write_ack = REG_WRITE_ACK;
	assign REG_READ_REQ = reg_read_req;
	assign reg_read_ack = REG_READ_ACK;

	always @(posedge CLK)
	begin
		if (RST) begin
			ulpi_initialized <= 1'b0;
			cnt <= 0;
			cnt2 <= 0;
			reg_write_req <= 0;
			reg_read_req <= 0;
		end else begin
			if (!ulpi_initialized) begin
				//
				// ready for new write?
				//
				
				if (!reg_write_req && !reg_write_ack) begin
					reg_address <= 6'h04; // function control
					reg_data_write <= 8'h48; // non driving, HS
					//reg_data_write <= 8'h49; // non driving, FS
					
					reg_write_req <= 1'b1;
				end else 
				
				//
				// Write ack'ed -> clear req.
				//
				
				if (reg_write_req && reg_write_ack) begin
					reg_write_req <= 0;
					ulpi_initialized <= 1'b1;
				end
			end else begin
				
				//
				// Read all registers.
				//
				
				if (reg_read_ack) begin
					reg_read_req <= 1'b0;
				end else if (!reg_read_req && reg_address != 6'h10) begin
					cnt <= cnt + 1'b1;
					if (!cnt) begin
						cnt2 <= cnt2 + 1'b1;
						
						reg_read_req <= 1'b1; 
						reg_address <= cnt2;
					end
				end
			end
		end
	end


endmodule
