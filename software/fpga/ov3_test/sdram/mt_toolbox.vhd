library ieee;
	use ieee.std_logic_1164.all;
	use ieee.numeric_std.all;
	
package mt_toolbox is
	
	--
	-- basic types
	--
	subtype slv8_t  is std_logic_vector(7 downto 0);
	subtype slv16_t is std_logic_vector(15 downto 0);
	subtype slv32_t is std_logic_vector(31 downto 0);
	subtype byte_t  is unsigned(7 downto 0);
	subtype word_t  is unsigned(15 downto 0);
	subtype dword_t is unsigned(31 downto 0);
	type slv8_array_t  is array (natural range<>) of slv8_t;
	type slv16_array_t is array (natural range<>) of slv16_t;
	type slv32_array_t is array (natural range<>) of slv32_t;
	type byte_array_t  is array (natural range<>) of byte_t;
	type word_array_t  is array (natural range<>) of word_t;
	type dword_array_t is array (natural range<>) of dword_t;
	
	--
	-- simple helper functions
	--
	function log2(x: natural) return positive;
	function log4(x: natural) return positive;
	function log2nat(x: natural) return natural;
	function log4nat(x: natural) return natural;
	function max(left, right: integer) return integer;
	function min(left, right: integer) return integer;
	function reverse_vector(a: in std_logic_vector) return std_logic_vector;
	function reverse_vector(a: in unsigned) return unsigned;
	function zeropad(arg: unsigned; new_size: NATURAL) return unsigned;
	function zeropad(arg: signed; new_size: NATURAL) return signed;
	function parity(a: in std_logic_vector) return std_logic;
	function bin2gray(x : unsigned) return unsigned;
	function gray2bin(x : unsigned) return unsigned;
	
	--
	-- type conversion helper
	--
	function to_slv8(x: std_logic) return std_logic_vector;
	function to_slv8(x: std_logic_vector) return std_logic_vector;
	function to_slv8(x: unsigned) return std_logic_vector;
	function to_slv8(x: signed) return std_logic_vector;
	function to_slv8(x: natural) return std_logic_vector;
	function to_slv16(x: std_logic) return std_logic_vector;
	function to_slv16(x: std_logic_vector) return std_logic_vector;
	function to_slv16(x: unsigned) return std_logic_vector;
	function to_slv16(x: signed) return std_logic_vector;
	function to_slv16(x: natural) return std_logic_vector;
	function to_slv32(x: std_logic) return std_logic_vector;
	function to_slv32(x: std_logic_vector) return std_logic_vector;
	function to_slv32(x: unsigned) return std_logic_vector;
	function to_slv32(x: signed) return std_logic_vector;
	function to_slv32(x: natural) return std_logic_vector;
	
	--
	-- common attributes
	--
	attribute syn_ramstyle                : string;
	attribute buffer_type                 : string;
	attribute equivalent_register_removal : string;
	attribute iob                         : string;
	attribute keep                        : string;
	attribute keep_hierarchy              : string;
	attribute max_fanout                  : string;
	attribute register_balancing          : string;
	attribute S                           : string;
	attribute shreg_extract               : string;
	attribute use_dsp48                   : string;

end mt_toolbox;

package body mt_toolbox is
	
	--
	-- simple helper functions
	--
	
	-- calculate ceiling base 2 logarithm (returns always >=1)
	function log2(x: natural) return positive is
		variable x_tmp: natural;
		variable y: positive;
	begin
		x_tmp := x-1;
		y := 1;
		while x_tmp > 1 loop
			y := y+1;
			x_tmp := x_tmp/2;
		end loop;
		return y;
	end;
	
	-- calculate ceiling base 4 logarithm (returns always >=1)
	function log4(x: natural) return positive is
		variable x_tmp: natural;
		variable y: positive;
	begin
		if x < 4 then
			return 1;
		else
			x_tmp := x-3;
			y := 1;
			while x_tmp > 3 loop
				y := y+1;
				x_tmp := x_tmp/4;
			end loop;
			return y;
		end if;
	end;
	
	-- calculate ceiling base 2 logarithm
	function log2nat(x: natural) return natural is
	begin
		if x<=1 
			then return 0;
			else return log2(x);
		end if;
	end;
	
	-- calculate ceiling base 4 logarithm
	function log4nat(x: natural) return natural is
	begin
		if x<=1 
			then return 0;
			else return log4(x);
		end if;
	end;  
	
	-- min/max
	function max(left, right: integer) return integer is
	begin
		if left > right then return left;
		else return right;
		end if;
	end MAX;
	function min(left, right: integer) return integer is
	begin
		if left < right then return left;
		else return right;
		end if;
	end min;

	
	-- bit-reverse 'std_logic_vector'
	function reverse_vector(a: in std_logic_vector) return std_logic_vector is
		variable result: std_logic_vector(a'reverse_range);
	begin
		for i in a'range loop
			result(i) := a(i);
		end loop;
		return result;
	end;
	
	-- bit-reverse 'unsigned'
	function reverse_vector(a: in unsigned) return unsigned is
		variable result: unsigned(a'high downto a'low);
	begin
		for i in a'range loop
			result(a'high-(i-a'low)) := a(i);
		end loop;
		return result;
	end;
	
	-- resize arg by padding zeros
	function zeropad(arg: signed; new_size: NATURAL) return signed is
		variable result : signed(new_size-1 downto 0);
	begin
		result := (others=>'0');
		result(result'left downto result'left+1-arg'length) := arg;
		return result;
	end zeropad;
	
	-- resize arg by padding zeros
	function zeropad(arg: unsigned; new_size: NATURAL) return unsigned is
		variable result : unsigned(new_size-1 downto 0);
	begin
		result := (others=>'0');
		result(result'left downto result'left+1-arg'length) := arg;
		return result;
	end zeropad;
	
	-- xors all bits of 'std_logic_vector'
	function parity (a: in std_logic_vector) return std_logic is
		variable y : std_logic := '0';
	begin
		for i in a'range loop
			y := y xor a(i);
		end loop;
		return y;
	end parity;
	
	-- convert binary number to gray code
	function bin2gray(x : unsigned) return unsigned is 
	begin
		return x xor ('0' & x(x'high downto 1));
	end bin2gray;
	
	-- convert gray code to binary number
	function gray2bin(x : unsigned) return unsigned is 
		variable res : unsigned(x'range);
	begin
		res(x'high) := x(x'high);
		for i in x'high-1 downto 0 loop
			res(i) := x(i) xor res(i+1);
		end loop;
		return res;
	end gray2bin;
	
	-- to_slv8 (pack basic types into "std_logic_vector(7 downto 0)")
	function to_slv8(x: std_logic) return std_logic_vector is
		variable res : std_logic_vector(7 downto 0);
	begin
		res := (0=>x,others=>'0');
		return res;
	end to_slv8;
	function to_slv8(x: std_logic_vector) return std_logic_vector is
		variable res : std_logic_vector(7 downto 0);
	begin
		res := (others=>'0');
		res(x'length-1 downto 0) := x;
		return res;
	end to_slv8;
	function to_slv8(x: unsigned) return std_logic_vector is
	begin
		return to_slv8(std_logic_vector(x));
	end to_slv8;
	function to_slv8(x: signed) return std_logic_vector is
	begin
		return to_slv8(std_logic_vector(x));
	end to_slv8;
	function to_slv8(x: natural) return std_logic_vector is
	begin
		return to_slv32(to_unsigned(x,8));
	end to_slv8;
	
	-- to_slv16 (pack basic types into "std_logic_vector(15 downto 0)")
	function to_slv16(x: std_logic) return std_logic_vector is
		variable res : std_logic_vector(15 downto 0);
	begin
		res := (0=>x,others=>'0');
		return res;
	end to_slv16;
	function to_slv16(x: std_logic_vector) return std_logic_vector is
		variable res : std_logic_vector(15 downto 0);
	begin
		res := (others=>'0');
		res(x'length-1 downto 0) := x;
		return res;
	end to_slv16;
	function to_slv16(x: unsigned) return std_logic_vector is
	begin
		return to_slv16(std_logic_vector(x));
	end to_slv16;
	function to_slv16(x: signed) return std_logic_vector is
	begin
		return to_slv16(std_logic_vector(x));
	end to_slv16;
	function to_slv16(x: natural) return std_logic_vector is
	begin
		return to_slv16(to_unsigned(x,16));
	end to_slv16;
	
	-- to_slv32 (pack basic types into "std_logic_vector(31 downto 0)")
	function to_slv32(x: std_logic) return std_logic_vector is
		variable res : std_logic_vector(31 downto 0);
	begin
		res := (0=>x,others=>'0');
		return res;
	end to_slv32;
	function to_slv32(x: std_logic_vector) return std_logic_vector is
		variable res : std_logic_vector(31 downto 0);
	begin
		res := (others=>'0');
		res(x'length-1 downto 0) := x;
		return res;
	end to_slv32;
	function to_slv32(x: unsigned) return std_logic_vector is
	begin
		return to_slv32(std_logic_vector(x));
	end to_slv32;
	function to_slv32(x: signed) return std_logic_vector is
	begin
		return to_slv32(std_logic_vector(x));
	end to_slv32;
	function to_slv32(x: natural) return std_logic_vector is
	begin
		return to_slv32(to_unsigned(x,32));
	end to_slv32;
end mt_toolbox;

