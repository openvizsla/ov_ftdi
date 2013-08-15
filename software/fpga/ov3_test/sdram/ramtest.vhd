library ieee;
	use ieee.std_logic_1164.all;
	use ieee.std_logic_misc.all;
	use ieee.numeric_std.all;
library work;
	use work.all;
	use work.mt_toolbox.all;

entity openvizsla_ramtest is
	port (
		-- input clock
		clk_13 : in    std_logic;
		
		-- status LEDs
		led0   : out   std_logic;
		led1   : out   std_logic;
		led2   : out   std_logic;
	
		-- SDR memory interface
		SD_CLK : out   std_logic;
		SD_CS  : out   std_logic;
		SD_WE  : out   std_logic;
		SD_CAS : out   std_logic;
		SD_RAS : out   std_logic;
		SD_DQM : out   std_logic_vector(1 downto 0);
		SD_BA  : out   std_logic_vector(1 downto 0);
		SD_A   : out   std_logic_vector(12 downto 0);
		SD_DQ  : inout std_logic_vector(15 downto 0)
	);
end openvizsla_ramtest;

architecture rtl of openvizsla_ramtest is

	-- generate clocks
	signal clk_91 : std_logic;
	signal clk_91_inv : std_logic;
	signal rst_91 : std_logic;

	-- memory interface - write request
	signal user_wreq   : std_logic;
	signal user_wstart : std_logic;
	signal user_wdone  : std_logic;
	signal user_waddr  : unsigned(23 downto 0);
	signal user_wsize  : unsigned(9 downto 0);
	signal user_wen    : std_logic;
	signal user_wdata  : std_logic_vector(15 downto 0);

	-- memory interface - read request
	signal user_rreq   : std_logic;
	signal user_rstart : std_logic;
	signal user_rdone  : std_logic;
	signal user_raddr  : unsigned(23 downto 0);
	signal user_rsize  : unsigned(9 downto 0);
	signal user_rvalid : std_logic;
	signal user_rdata  : std_logic_vector(15 downto 0);
	
	-- reset
	signal status     : std_logic;
	signal err_strobe : std_logic;
	signal err_latch  : std_logic;
			
begin
	
	-- connect status LEDs
	led0 <= not status;
	led1 <= not err_strobe;
	led2 <= not err_latch;
	
	-- housekeeping
	cg: entity midimux_clklogic
		port map (
			-- clock input
			clk_in_13 => clk_13,
		
			-- generated clocks
			clk_91 => clk_91,
			rst_91 => rst_91
		);
		
	-- forward clock to SDRAM
--	SD_CLK <= clk_91;
	
	-- forward inverted clock zo SDRAM
	clk_91_inv <= not clk_91;
	buf_vclk1: ODDR2
		port map (Q=>sd_clk,C0=>clk_91,C1=>clk_91_inv,D0=>'0',D1=>'1',CE=>'1',R=>'0',S=>'0'); 

	-- SDRAM control
	sdrctrl: entity mt_extram_sdrctrl
		port map (
			-- clocks
			clk			=> clk_91,
			rst			=> rst_91,
			
			-- user interface - write request
			user_wreq   => user_wreq,
			user_wstart => user_wstart,
			user_wdone  => user_wdone,
			user_waddr  => user_waddr,
			user_wsize  => user_wsize,
			user_wen    => user_wen,
			user_wdata  => user_wdata,
		
			-- user interface - read request
			user_rreq   => user_rreq,
			user_rstart => user_rstart,
			user_rdone  => user_rdone,
			user_raddr  => user_raddr,
			user_rsize  => user_rsize,
			user_rvalid => user_rvalid,
			user_rdata  => user_rdata,
			
			-- SDR memory interface
			SD_CKE  => open,
			SD_CS	  => SD_CS,
			SD_WE   => SD_WE,
			SD_CAS  => SD_CAS,
			SD_RAS  => SD_RAS,
			SD_DQM  => SD_DQM,
			SD_BA	  => SD_BA,
			SD_A    => SD_A,
			SD_DQ   => SD_DQ
		);
		
	-- SDRAM test
	tst: entity mt_extram_test
		port map (
			-- clocks
			clk         => clk_91,
			rst         => rst_91,
			
			-- user interface - write request
			user_wreq   => user_wreq,
			user_wstart => user_wstart,
			user_wdone  => user_wdone,
			user_waddr  => user_waddr,
			user_wsize  => user_wsize,
			user_wen    => user_wen,
			user_wdata  => user_wdata,
		
			-- user interface - read request
			user_rreq   => user_rreq,
			user_rstart => user_rstart,
			user_rdone  => user_rdone,
			user_raddr  => user_raddr,
			user_rsize  => user_rsize,
			user_rvalid => user_rvalid,
			user_rdata  => user_rdata,
			
			-- reset
			status      => status,
			err_strobe  => err_strobe,
			err_latch   => err_latch
		);
	
end rtl;








