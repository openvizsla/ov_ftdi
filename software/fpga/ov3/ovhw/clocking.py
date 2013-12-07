from migen.fhdl.std import *

class ClockGen(Module):
    def __init__(self, clkin):
        self.clk_sys = Signal()
        self.clk_sdram = Signal()
        self.clk_sdram_sample = Signal()
        self.cd_sys = ClockDomain()
        self.pll_locked = Signal()

        clkout0, clkout2 = Signal(), Signal()

        feedback = Signal()

        # VCO 400.1000MHz
        # PFD 19..400MHz
        # 50MHz in, /1 50MHz PFD, x16 800MHz VCO, /8 100MHz CLKOUT
        self.specials.pll = Instance("PLL_BASE",
            Instance.Input("CLKIN", clkin),
            Instance.Input("CLKFBIN", feedback),
            Instance.Input("RST", 0),
            Instance.Output("CLKFBOUT", feedback),
            Instance.Output("CLKOUT0", clkout0),
            Instance.Output("CLKOUT1", self.clk_sdram),
            Instance.Output("CLKOUT2", clkout2),
            Instance.Output("LOCKED", self.pll_locked),
            Instance.Parameter("BANDWIDTH", "LOW"),
            Instance.Parameter("COMPENSATION", "INTERNAL"),
            Instance.Parameter("CLK_FEEDBACK", "CLKFBOUT"),
            Instance.Parameter("DIVCLK_DIVIDE", 1),
            Instance.Parameter("CLKFBOUT_MULT", 16),
            Instance.Parameter("CLKOUT0_DIVIDE", 8),
            Instance.Parameter("CLKOUT0_PHASE", 0.0),
            Instance.Parameter("CLKOUT1_DIVIDE", 8),
            Instance.Parameter("CLKOUT1_PHASE", 180.0),
            Instance.Parameter("CLKOUT2_DIVIDE", 8),
            Instance.Parameter("CLKOUT2_PHASE", 180.0),
            Instance.Parameter("CLKOUT3_DIVIDE", 24),
            Instance.Parameter("CLKOUT3_PHASE", 0.0),
        )
        self.specials += [
            Instance("BUFG", Instance.Input("I", clkout0),
                             Instance.Output("O", self.clk_sys)),
            Instance("BUFG", Instance.Input("I", clkout2),
                             Instance.Output("O", self.clk_sdram_sample)),
        ]

        # Reset generator: 4 cycles in reset after PLL is locked
        rst_ctr = Signal(max=4)
        self.clock_domains.cd_rst = ClockDomain()
        self.cd_sys.rst.reset = 1
        self.sync.rst += If(rst_ctr == 3,
                            self.cd_sys.rst.eq(0)
                         ).Else(
                            rst_ctr.eq(rst_ctr+1)
                         )
        self.comb += [
            self.cd_rst.clk.eq(self.clk_sys),
            self.cd_rst.rst.eq(~self.pll_locked),
            self.cd_sys.clk.eq(self.clk_sys),
        ]
