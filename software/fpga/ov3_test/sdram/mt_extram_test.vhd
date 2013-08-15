library ieee;
	use ieee.std_logic_1164.all;
	use ieee.std_logic_misc.all;
	use ieee.numeric_std.all;
	use ieee.math_real.all;
library work;
	use work.all;
	use work.mt_toolbox.all;

entity mt_extram_test is
	port (
		-- clocks
		clk			: in  std_logic;
		rst			: in  std_logic;
		
		-- user interface - write request
		user_wreq   : out std_logic;
		user_wstart : in  std_logic;
		user_wdone  : in  std_logic;
		user_waddr  : out unsigned(23 downto 0);
		user_wsize  : out unsigned(9 downto 0);
		user_wen    : in  std_logic;
		user_wdata  : out std_logic_vector(15 downto 0);
	
		-- user interface - read request
		user_rreq   : out std_logic;
		user_rstart : in  std_logic;
		user_rdone  : in  std_logic;
		user_raddr  : out unsigned(23 downto 0);
		user_rsize  : out unsigned(9 downto 0);
		user_rvalid : in  std_logic;
		user_rdata  : in  std_logic_vector(15 downto 0);
		
		-- reset
		status		: out std_logic;
		err_strobe	: out std_logic;
		err_latch	: out std_logic
	);
end mt_extram_test;

architecture rtl of mt_extram_test is

	-- LFSRs
	signal lfsr_sync : std_logic;
	signal lfsr_ena  : std_logic;
	signal lfsr_oval : std_logic_vector(15 downto 0);
	
	-- test logic
	type state_t is (IDLE,READ,WRITE);
	signal state  : state_t;
	signal addr   : unsigned(23 downto 0);
	signal active : std_logic;
	signal error  : std_logic;
	signal lerror : std_logic;
	
begin	

	-- reset
	status     <= '1' when (state=WRITE) else '0';
	err_strobe <= error;
	err_latch  <= lerror;
		
	--
	-- test
	--
	
	process(clk,rst)
	begin
		if rst='1' then
			lfsr_sync	<= '0';
			user_wreq	<= '0';
			user_waddr	<= (others=>'0');
			user_wsize	<= to_unsigned(512,10);
			user_rreq	<= '0';
			user_raddr	<= (others=>'0');
			user_rsize	<= to_unsigned(512,10);
			state 		<= IDLE;
			active		<= '0';
			addr        <= (others=>'0');
			error		<= '0';
			lerror		<= '0';
		elsif rising_edge(clk) then
			
			lfsr_sync <= '0';
			
			if state=IDLE then
				state  <= WRITE;
				addr   <= (others=>'0');
				active <= '0';
				lfsr_sync <= '1';
			elsif state=WRITE then
				if active='0' then 
					user_waddr <= addr;
					user_wreq  <= '1';
					active     <= '1';
				elsif user_wdone='1' then
					user_wreq  <= '0';
					active     <= '0';
					addr       <= addr + 512;
					if addr=(2**24-512) then
						addr  <= (others=>'0');
						state <= READ;
						lfsr_sync <= '1';
					end if;
				end if;
			elsif state=READ then
				if active='0' then 
					user_raddr <= addr;
					user_rreq  <= '1';
					active     <= '1';
				elsif user_rdone='1' then
					user_rreq  <= '0';
					active     <= '0';
					addr       <= addr + 512;
					if addr=(2**24-512) then
						addr  <= (others=>'0');
						state <= WRITE;
						lfsr_sync <= '1';
					end if;
				end if;
			end if;
			
			if user_rvalid='1' and user_rdata/=lfsr_oval then
				error  <= '1';
				lerror <= '1';
			else
				error  <= '0';
			end if;
		end if;
	end process;
	
	-- connect remaining LFSR ports
	lfsr_ena   <= user_rvalid or user_wen;
	user_wdata <= lfsr_oval;
	
	--
	-- LFSRs
	--

	i_lfsr1: entity mt_lfsr
		generic map (LEN_POLY=>26, LEN_OUT=>8)
		port map (
			clk 	=> clk,
			reset 	=> rst,
			enable	=> lfsr_ena,
			restart	=> lfsr_sync,
			oval	=> lfsr_oval(7 downto 0)
		);
	i_lfsr2: entity mt_lfsr
		generic map (LEN_POLY=>25, LEN_OUT=>8)
		port map (
			clk 	=> clk,
			reset 	=> rst,
			enable	=> lfsr_ena,
			restart	=> lfsr_sync,
			oval	=> lfsr_oval(15 downto 8)
		);
	
end rtl;








