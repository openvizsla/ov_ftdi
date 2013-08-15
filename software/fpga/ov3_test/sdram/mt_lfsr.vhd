library ieee;
	use ieee.std_logic_1164.all;
	use ieee.numeric_std.all;
library work;
	use work.mt_toolbox.all;

entity mt_lfsr is
	generic (
		LEN_POLY	: natural;
		LEN_OUT		: natural
	);	
	port (
		-- common
		clk 		: in  std_logic;
		reset 		: in  std_logic;
		
		-- config
		enable		: in  std_logic:='1';
		restart		: in  std_logic:='0';
		seed		: in  std_logic_vector(LEN_POLY-1 downto 0) := (0=>'1',others=>'0');
		
		-- output
		oval		: out std_logic_vector(LEN_OUT-1 downto 0)
	);
end mt_lfsr;

architecture rtl of mt_lfsr is

	-- internal type
	subtype poly_t is std_logic_vector(LEN_POLY-1 downto 0);

	-- get polynom for given length
	function getPoly return poly_t is
	begin
		case LEN_POLY is
			when  2 => return "11";
			when  3 => return "110";
			when  4 => return "1100";
			when  5 => return "10100";
			when  6 => return "110000";
			when  7 => return "1100000";
			when  8 => return "10111000";
			when  9 => return "100010000";
			when 10 => return "1001000000";
			when 11 => return "10100000000";
			when 12 => return "110010100000";
			when 13 => return "1101100000000";
			when 14 => return "11010100000000";
			when 15 => return "110000000000000";
			when 16 => return "1011010000000000";
			when 17 => return "10010000000000000";
			when 18 => return "100000010000000000";
			when 19 => return "1110010000000000000";
			when 20 => return "10010000000000000000";
			when 21 => return "101000000000000000000";
			when 22 => return "1100000000000000000000";
			when 23 => return "10000100000000000000000";
			when 24 => return "110110000000000000000000";
			when 25 => return "1001000000000000000000000";
			when 26 => return "11100010000000000000000000";
			when 27 => return "111001000000000000000000000";
			when 28 => return "1001000000000000000000000000";
			when 29 => return "10100000000000000000000000000";
			when 30 => return "110010100000000000000000000000";
			when 31 => return "1001000000000000000000000000000";
			when 32 => return "10100011000000000000000000000000";
			when 33 => return "100000000000010000000000000000000";
			when 34 => return "1001100010000000000000000000000000";
			when 35 => return "10100000000000000000000000000000000";
			when 36 => return "100000000001000000000000000000000000";
			when 37 => return "1100101000000000000000000000000000000";
			when 38 => return "11000110000000000000000000000000000000";
			when 39 => return "100010000000000000000000000000000000000";
			when 40 => return "1001110000000000000000000000000000000000";
			when others =>
				report "mt_lfsr: unsupported polynom length" severity FAILURE;
				return (others=>'0');
		end case;
	end;
	
	-- signals
	constant poly : poly_t := getPoly;
	signal   taps : poly_t;
	signal   oreg : std_logic_vector(oval'range);

	-- time XST
	attribute equivalent_register_removal of oreg :  signal is "no";
	attribute equivalent_register_removal of rtl : architecture is "no";
	attribute S of oreg: signal is "TRUE";
	
begin
	
	-- update status
	process(clk, SEED)
		variable nxt : poly_t;
	begin
		if rising_edge(clk) then
			if reset='1' or restart='1' then
				taps <= SEED;
				oreg <= SEED(SEED'left downto SEED'left+1-LEN_OUT);
			elsif enable='1' then
				-- update taps
				nxt := taps;
				for i in 1 to LEN_OUT loop
					if nxt(0)='1'
						then nxt := ('0'&nxt(nxt'high downto 1)) xor poly;
						else nxt := ('0'&nxt(nxt'high downto 1));
					end if;
				end loop;
				taps <= nxt;
				
				-- update output
				oreg <= taps(oval'range);
			end if;
		end if;
	end process;
	
	-- set output
	oval <= oreg;

end rtl;
