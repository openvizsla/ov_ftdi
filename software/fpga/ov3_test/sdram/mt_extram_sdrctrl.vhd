library ieee;
	use ieee.std_logic_1164.all;
	use ieee.std_logic_misc.all;
	use ieee.numeric_std.all;
	use ieee.math_real.all;
library work;
	use work.all;
	use work.mt_toolbox.all;

entity mt_extram_sdrctrl is
	port (
		-- clocks
		clk			: in  std_logic;
		rst			: in  std_logic;
		
		-- WARNING:
		-- one request can only read/write in a single column (512 words)
		-- so (first-addr mod 512) must be equal to (last-addr mod 512)
		
		-- user interface - write request
		user_wreq   : in  std_logic;						-- write request (must be kept asserted until 'user_wstart' is set)
		user_wstart : out std_logic;						-- starting to handle request
		user_wdone  : out std_logic;						-- request completely handled
		user_waddr  : in  unsigned(23 downto 0);			-- request address (word address, NOT byte address)
		user_wsize  : in  unsigned(9 downto 0);				-- request size in words [1-512]
		user_wen    : out std_logic;						-- data on 'user_wdata' handled, next word expeced on next cycle
		user_wdata  : in  std_logic_vector(15 downto 0);	-- dataword
	
		-- user interface - read request
		user_rreq   : in  std_logic;						-- read request (must be kept asserted until 'user_wstart' is set)
		user_rstart : out std_logic;						-- starting to handle request
		user_rdone  : out std_logic;						-- request completely handled
		user_raddr  : in  unsigned(23 downto 0);			-- address (word address, NOT byte address)
		user_rsize  : in  unsigned(9 downto 0);				-- request size in words [1-512]
		user_rvalid : out std_logic;						-- new dataword on 'user_rdata' 
		user_rdata  : out std_logic_vector(15 downto 0);	-- dataword
	
		-- SDR memory interface
		SD_CKE : out   std_logic;
		SD_CS  : out   std_logic;
		SD_WE  : out   std_logic;
		SD_CAS : out   std_logic;
		SD_RAS : out   std_logic;
		SD_DQM : out   std_logic_vector(1 downto 0);
		SD_BA  : out   std_logic_vector(1 downto 0);
		SD_A   : out   std_logic_vector(12 downto 0);
		SD_DQ  : inout std_logic_vector(15 downto 0)
	);
end mt_extram_sdrctrl;

architecture rtl of mt_extram_sdrctrl is

	--
	-- configuration
	--

	-- config
	constant MODEREG : std_logic_vector(12 downto 0) := "0000000110111";	-- Full Page, Sequential, CAS=3

	-- timing
	constant Tck  : real := 1000.0 / 91.0;		-- clock period
	constant Trst : real := 100000.0;			-- 100us reset period
	constant Tmrd : real := 2.0 * Tck;			-- load mode register command period
	constant Trfc : real := 70.0;				-- auto refresh command period
	constant Trp  : real := 20.0;				-- precharge command period
	constant Trcd : real := 20.0;				-- active to read/write
	constant Twr  : real := Tck + 7.0;			-- write recovery time
	constant Tdal : real := Trp + Twr;			-- active to read/write
	constant Tref : real := 15600.0 * 0.9;		-- refresh period (per row)
	constant CL   : integer := 3;				-- CAS Latency
	
	--
	-- internal declarations
	--
	
	-- timing
	constant TCNT_rst : natural := natural(ceil(Trst / Tck));
	constant TCNT_mrd : natural := natural(ceil(Tmrd / Tck));
	constant TCNT_rfc : natural := natural(ceil(Trfc / Tck));
	constant TCNT_rp  : natural := natural(ceil(Trp  / Tck));
	constant TCNT_rcd : natural := natural(ceil(Trcd / Tck));
	constant TCNT_dal : natural := natural(ceil(Tdal / Tck));
	constant TCNT_ref : natural := natural(ceil(Tref / Tck));
	
	-- internal types
	subtype cmd_t is std_logic_vector(3 downto 0);
	
	-- states
	type initstate_t is (
		sReset,     sWait100,
		sPrecharge, sWaitRP,
		sRefresh1,  sWaitRFC1,
		sRefresh2,  sWaitRFC2,
		sLoadMode,  sWaitMRD,
		sDone
	);
	type state_t is (
		sInit, sIdle, sStartCmd,
		sRefresh,    sWaitRFC,
		sActive,     sWaitRCD,
		sStartW,     sWrite,
		sStartR,     sRead,
		sTerminate,
		sPrecharge,  sWaitRP,
		sWaitRDone,  sNOP
	);
	
	-- commands
	constant SDCMD_INHIBIT		: cmd_t := "1111";
	constant SDCMD_NOP			: cmd_t := "0111";
	constant SDCMD_ACTIVE		: cmd_t := "0011";
	constant SDCMD_READ			: cmd_t := "0101";
	constant SDCMD_WRITE		: cmd_t := "0100";
	constant SDCMD_TERMINATE	: cmd_t := "0110";
	constant SDCMD_PRECHARGE	: cmd_t := "0010";
	constant SDCMD_REFRESH		: cmd_t := "0001";
	constant SDCMD_LOADMODE		: cmd_t := "0000";
	
	--
	-- helper
	--
	
	-- get read delay
	function READ_DELAY return integer is
	begin
-- synthesis translate_off 
		return CL+1;
-- synthesis translate_on 
		return CL+1;
	end READ_DELAY;
	
	
	--
	-- signals
	--
		
	-- init state machine
	signal istate : initstate_t;
	signal icount : unsigned(log2(TCNT_rst)-1 downto 0);
	
	-- main state machine
	signal state : state_t;
	signal count : unsigned(9 downto 0);
	
	-- auto-refresh counter
	signal ar_cnt : unsigned(log2(TCNT_ref)-1 downto 0);
	signal ar_req : std_logic;
	signal ar_ack : std_logic;
	
	-- command latch
	signal cmd_write : std_logic;
	signal cmd_addr  : unsigned(23 downto 0);
	signal cmd_size  : unsigned(9 downto 0);
	
	-- read logic
	signal ren   : std_logic_vector(READ_DELAY-1 downto 0);
	
	-- SDRAM signals
	signal cke  : std_logic;
	signal cmd  : cmd_t;
	signal ba   : std_logic_vector(1 downto 0);
	signal ad   : std_logic_vector(12 downto 0);
	signal dqt  : std_logic;
	signal dqo  : std_logic_vector(15 downto 0);
	signal dqi  : std_logic_vector(15 downto 0);
	
	-- move registers into IOBs
	attribute iob: string;
	attribute iob of cke: signal is "true"; 
	attribute iob of cmd: signal is "true"; 
	attribute iob of ba:  signal is "true"; 
	attribute iob of ad:  signal is "true";
	attribute iob of dqo: signal is "true";
	attribute iob of dqi: signal is "true";
	attribute iob of dqt: signal is "true";
	
begin	

	--
	-- state machines
	--
	
	-- init state-machine
	process(clk, rst)
	begin
		if rst='1' then
			istate <= sReset;
			icount <= (others=>'0');
		elsif rising_edge(clk) then
			-- update status
			case istate is
				-- wait states
				when sWait100 => 
					if icount=0 
						then istate <= sPrecharge;
						else icount <= icount - 1;
					end if;
				when sWaitRP => 
					if icount=0 
						then istate <= sRefresh1;
						else icount <= icount - 1;
					end if;
				when sWaitRFC1 => 
					if icount=0 
						then istate <= sRefresh2;
						else icount <= icount - 1;
					end if;
				when sWaitRFC2 => 
					if icount=0 
						then istate <= sLoadMode;
						else icount <= icount - 1;
					end if;
				when sWaitMRD => 
					if icount=0 
						then istate <= sDone;
						else icount <= icount - 1;
					end if;
					
				-- worker stats
				when sReset =>
					icount <= to_unsigned(TCNT_rst-2, icount'length);
					istate <= sWait100;
				when sPrecharge => 
					icount <= to_unsigned(TCNT_rp-2, icount'length);
					istate <= sWaitRP;
				when sRefresh1 => 
					icount <= to_unsigned(TCNT_rfc-2, icount'length);
					istate <= sWaitRFC1;
				when sRefresh2 => 
					icount <= to_unsigned(TCNT_rfc-2, icount'length);
					istate <= sWaitRFC2;
				when sLoadMode => 
					icount <= to_unsigned(TCNT_mrd-2, icount'length);
					istate <= sWaitMRD;
				
				-- other states
				when others => 
					null;
			end case;
		end if;
	end process;	
	
	-- main state machine
	process(clk, rst)
	begin
		if rst='1' then
			state     <= sInit;
			count     <= (others=>'0');
			ar_ack    <= '0';
			cmd_write <= '0';
			cmd_addr  <= (others=>'0');
			cmd_size  <= (others=>'0');
			user_wstart <= '0';
			user_rstart <= '0';
			user_wdone  <= '0';
			user_rdone  <= '0';
		elsif rising_edge(clk) then
			-- apply default values
			ar_ack <= '0';
			user_wstart <= '0';
			user_rstart <= '0';
			user_wdone  <= '0';
			user_rdone  <= '0';
			
			-- update main-status
			case state is
				when sInit =>
					-- wait until init-stata-machine has finished
					if istate=sDone then
						--> init done, goto idle-state
						state <= sIdle;
					end if;
					
				when sIdle =>
					-- check if there's something to do
					if ar_req='1' then
						--> start auto refresh
						state <= sRefresh;
					elsif user_wreq='1' then
						--> start write operation
						state       <= sStartCmd;
						cmd_write   <= '1';
						user_wstart <= '1';
					elsif user_rreq='1' then
						--> start read operation
						state       <= sStartCmd;
						cmd_write   <= '0';
						user_rstart <= '1';
					end if;
					
				when sStartCmd =>
					-- latch command-params while user_rstart/user_wstart is high
					if cmd_write='1' then
						cmd_addr <= user_waddr;
						cmd_size <= user_wsize;
					else
						cmd_addr <= user_raddr;
						cmd_size <= user_rsize;
					end if;
					state <= sActive;

				when sRefresh =>
					-- wait Trfc after auto refresh
					count  <= to_unsigned(TCNT_rfc-2, count'length);
					state  <= sWaitRFC;
					ar_ack <= '1';
					
				when sWaitRFC => 
					-- wait until counter has ellapsed
					if count=0 
						then state <= sIdle;
						else count <= count - 1;
					end if;
					
				when sActive =>
					-- issue active-command and wait Trcd
					count <= to_unsigned(TCNT_rcd-2, count'length);
					state <= sWaitRCD;
					
				when sWaitRCD => 
					-- wait until counter has ellapsed
					if count=0 then 
						if cmd_write='1'
							then state <= sStartW;
							else state <= sStartR;
						end if;
					else 
						count <= count - 1;
					end if;
					
				when sStartW =>
					-- issue write-command
					count <= cmd_size - 2;
					if cmd_size<2 
						then state <= sTerminate;
						else state <= sWrite;
					end if;
				
				when sWrite =>
					-- keep writing until counter has ellapsed
					if count=0 
						then state <= sTerminate;
						else count <= count - 1;
					end if;
					
				when sStartR =>
					-- issue read-command
					count <= cmd_size - 2;
					if cmd_size<2 
						then state <= sTerminate;
						else state <= sRead;
					end if;
				
				when sRead =>
					-- keep reading until counter has ellapsed
					if count=0 
						then state <= sTerminate;
						else count <= count - 1;
					end if;
				
				when sTerminate =>
					-- issue terminate-command
					state <= sPrecharge;
					if cmd_write='1' then
						user_wdone <= '1';
					end if;
				
				when sPrecharge =>
					-- issue precharge-command and wait Trp
					if TCNT_rp>=3 then
						count <= to_unsigned(TCNT_rp-3, count'length);
						state <= sWaitRP;
					else
						if cmd_write='1'
							then state <= sNOP;
							else state <= sWaitRDone;
						end if;
					end if;
					
				when sWaitRP => 
					-- wait until counter has ellapsed
					if count=0 then 
						if cmd_write='1'
							then state <= sNOP;
							else state <= sWaitRDone;
						end if;
					else 
						count <= count - 1;
					end if;
					
				when sWaitRDone =>
					if or_reduce(ren)='0' then
						user_rdone <= '1';
						state <= sNOP;
					end if;
					
				when sNOP =>
					state <= sIdle;
					
				when others => 
					null;
			end case;
		end if;
	end process;
	
	
	--
	-- SDRAM I/O
	--
	
	-- set output
	process(clk, rst)
	begin
		if rst='1' then
			cke <= '0';
			cmd <= SDCMD_INHIBIT;
			ba  <= (others=>'0');
			ad  <= (others=>'0');
			dqt <= '1';
			dqo <= (others=>'0');
		elsif rising_edge(clk) then
			-- update control outputs
			cke <= '1';
			case state is
				when sInit =>
					case istate is
						when sPrecharge => 
							cmd <= SDCMD_PRECHARGE;
							ba  <= "11";
							ad  <= "1111111111111";
						when sRefresh1 | sRefresh2=> 
							cmd <= SDCMD_REFRESH;
							ba  <= "11";
							ad  <= "1111111111111";
						when sLoadMode => 
							cmd <= SDCMD_LOADMODE;
							ba  <= "00";
							ad  <= MODEREG;
						when others =>
							cmd <= SDCMD_NOP;
							ba  <= "11";
							ad  <= "1111111111111";
					end case;
				when sRefresh => 
					cmd <= SDCMD_REFRESH;
					ba  <= "11";
					ad  <= "1111111111111";
				when sActive => 
					cmd <= SDCMD_ACTIVE;
					ba  <= std_logic_vector(cmd_addr(23 downto 22));
					ad  <= std_logic_vector(cmd_addr(21 downto 9));
				when sStartW => 
					cmd <= SDCMD_WRITE;
					ba  <= std_logic_vector(cmd_addr(23 downto 22));
					ad  <= std_logic_vector(resize(cmd_addr(8 downto 0),13));
				when sStartR => 
					cmd <= SDCMD_READ;
					ba  <= std_logic_vector(cmd_addr(23 downto 22));
					ad  <= std_logic_vector(resize(cmd_addr(8 downto 0),13));
				when sTerminate => 
					cmd <= SDCMD_TERMINATE;
					ba  <= "11";
					ad  <= "1111111111111";
				when sPrecharge => 
					cmd <= SDCMD_PRECHARGE;
					ba  <= std_logic_vector(cmd_addr(23 downto 22));
					ad  <= "1101111111111";
				when others =>
					cmd <= SDCMD_NOP;
					ba  <= "11";
					ad  <= "1111111111111";
			end case;
			
			-- update data output
			case state is
				when sStartW | sWrite => 
					dqt <= '0';
					dqo <= user_wdata;
				when others =>
					dqt <= '1';
					dqo <= (others=>'0');
			end case;
		end if;
	end process;	
	
	-- get input
	process(clk)
	begin
		if falling_edge(clk) then
			-- data input IOB register
			dqi <= SD_DQ;
		end if;
	end process;
	
	-- get input
	process(clk)
	begin
		if rising_edge(clk) then
			-- create read-enable signals
			if state=sStartR or state=sRead 
				then ren(0) <= '1';
				else ren(0) <= '0';
			end if;
			
			-- delay read-enable signals to match CAS-Latency
			ren(ren'high downto 1) <= ren(ren'high-1 downto 0);
			
			-- update user-output
			if ren(ren'high)='1' then
				user_rvalid	<= '1';
				user_rdata	<= dqi;
			else
				user_rvalid	<= '0';
				user_rdata	<= (others=>'-');
			end if;
		end if;
	end process;	
	
	-- create write-enable flag for user
	user_wen <= '1' when (state=sStartW or state=sWrite) else '0';

	-- connect output
	SD_CKE <= cke;
	SD_CS  <= cmd(3);
	SD_RAS <= cmd(2);
	SD_CAS <= cmd(1);
	SD_WE  <= cmd(0);
	SD_BA  <= ba;
	SD_A   <= ad;
	SD_DQM <= "00";
	SD_DQ  <= dqo when dqt='0' else (others=>'Z');

	
	--
	-- helper
	--
	
	-- auto-refresh timer
	process(clk, rst)
	begin
		if rst='1' then
			ar_cnt <= (others=>'0');
			ar_req <= '0';
		elsif rising_edge(clk) then
			if ar_cnt=0 then
				ar_cnt <= to_unsigned(TCNT_ref-1, ar_cnt'length);
				ar_req <= '1';
			else
				ar_cnt <= ar_cnt - 1;
				ar_req <= ar_req and (not ar_ack);
			end if;
		end if;
	end process;

end rtl;








