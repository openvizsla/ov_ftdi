from migen.fhdl.std import *

class ClockGen(Module):
    def __init__(self, clkin):
        self.clk_sys = Signal()
        self.clk_sdram = Signal()
        self.clk_sdram_sample = Signal()
        self.cd_sys = ClockDomain()
        self.pll_locked = Signal()

        clkout0, clkout2 = Signal(), Signal()
        dcm_locked = Signal()
        clkdcm = Signal()

        feedback = Signal()

        # Simple 2X: 12MHz -> 24MHz
        self.specials.dcm = Instance("DCM_SP",
            Instance.Input("CLKIN", clkin),
            Instance.Input("CLKFB", clkdcm),
            Instance.Input("RST", 0),
            Instance.Output("CLK2X", clkdcm),
            Instance.Output("LOCKED", dcm_locked),
            Instance.Parameter("CLK_FEEDBACK", "2X"),
        )

        # VCO 400.1000MHz
        # PFD 19..400MHz
        # 24MHz in, /1 24MHz PFD, x25 600MHz VCO, /6 100MHz CLKOUT
        self.specials.pll = Instance("PLL_BASE",
            Instance.Input("CLKIN", clkdcm),
            Instance.Input("CLKFBIN", feedback),
            Instance.Input("RST", ~dcm_locked),
            Instance.Output("CLKFBOUT", feedback),
            Instance.Output("CLKOUT0", clkout0),
            Instance.Output("CLKOUT1", self.clk_sdram),
            Instance.Output("CLKOUT2", clkout2),
            Instance.Output("LOCKED", self.pll_locked),
            Instance.Parameter("BANDWIDTH", "LOW"),
            Instance.Parameter("COMPENSATION", "DCM2PLL"),
            Instance.Parameter("CLK_FEEDBACK", "CLKFBOUT"),
            Instance.Parameter("DIVCLK_DIVIDE", 1),
            Instance.Parameter("CLKFBOUT_MULT", 25),
            Instance.Parameter("CLKOUT0_DIVIDE", 6),
            Instance.Parameter("CLKOUT0_PHASE", 0.0),
            Instance.Parameter("CLKOUT1_DIVIDE", 6),
            Instance.Parameter("CLKOUT1_PHASE", 180.0),
            Instance.Parameter("CLKOUT2_DIVIDE", 6),
            Instance.Parameter("CLKOUT2_PHASE", 180.0),
            Instance.Parameter("CLKOUT3_DIVIDE", 18),
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
