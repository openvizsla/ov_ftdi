-------------------------------------------------------------------------------
-- mt_reset_gen ---------------------------------------------------------------
-------------------------------------------------------------------------------

library ieee;
	use ieee.std_logic_1164.all;

entity mt_reset_gen is
	port (
		clk 		: in  std_logic;	-- some direct clock-input
		pll_locked	: in  std_logic;	-- PLLs locked?
		reset_pll	: out std_logic;	-- reset signal for PLLs
		reset_sys	: out std_logic		-- global reset signal
	);
end mt_reset_gen;

architecture rtl of mt_reset_gen is

	-- reset generation
	signal rst_roc2pll	: std_logic_vector(5 downto 0) := (others=>'1');	-- delay between rst_roc <-> rst_pll
	signal rst_pll2go	: std_logic_vector(5 downto 0) := (others=>'1'); 	-- delay between reset_pll <-> reset_I
	signal reset_pll_i	: std_logic := '1';									-- inner version of 'reset_pll'
	signal reset_sys_i	: std_logic;										-- inner version of 'reset_sys'
	
begin

	-- generate PLL-reset
	process(clk)
	begin
		if rising_edge(clk) then
			rst_roc2pll <= '0' & rst_roc2pll(rst_roc2pll'high downto 1);
			reset_pll_i <= rst_roc2pll(0);
		end if;
	end process;
	
	-- generate system-reset
	process(clk, reset_pll_i)
	begin
		if reset_pll_i = '1' then
			reset_sys_i <= '1';
			rst_pll2go  <= (others=>'1');
		elsif rising_edge(clk) then
			if pll_locked='0' then
				rst_pll2go  <= (others=>'1');
				reset_sys_i <= '1';
			else
				rst_pll2go  <= '0' & rst_pll2go(rst_pll2go'high downto 1);
				reset_sys_i <= rst_pll2go(0);
			end if;
		end if;
	end process;
		
	-- output reset-signal
	reset_sys <= reset_sys_i;
		
	-- output PLL-reset
	reset_pll <= reset_pll_i;
end;


-------------------------------------------------------------------------------
-- mt_reset_sync --------------------------------------------------------------
-------------------------------------------------------------------------------

library ieee;
	use ieee.std_logic_1164.all;

entity mt_reset_sync is
	port (
		clk 	: in  std_logic;
		rst_in	: in  std_logic;
		rst_out	: out std_logic
	);
end mt_reset_sync;

architecture rtl of mt_reset_sync is
	signal taps : std_logic_vector(3 downto 0);
begin
	process(clk, rst_in)
	begin
		if rst_in='1' then
			taps    <= (others=>'1');
			rst_out <= '1';
		elsif rising_edge(clk) then
			taps    <= "0" & taps(taps'high downto 1);
			rst_out <= taps(0);
		end if;
	end process;
end;
