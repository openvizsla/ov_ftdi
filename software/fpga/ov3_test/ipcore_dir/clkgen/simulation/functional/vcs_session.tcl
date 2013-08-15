gui_open_window Wave
gui_sg_create clkgen_group
gui_list_add_group -id Wave.1 {clkgen_group}
gui_sg_addsignal -group clkgen_group {clkgen_tb.test_phase}
gui_set_radix -radix {ascii} -signals {clkgen_tb.test_phase}
gui_sg_addsignal -group clkgen_group {{Input_clocks}} -divider
gui_sg_addsignal -group clkgen_group {clkgen_tb.CLK_IN1}
gui_sg_addsignal -group clkgen_group {{Output_clocks}} -divider
gui_sg_addsignal -group clkgen_group {clkgen_tb.dut.clk}
gui_list_expand -id Wave.1 clkgen_tb.dut.clk
gui_sg_addsignal -group clkgen_group {{Status_control}} -divider
gui_sg_addsignal -group clkgen_group {clkgen_tb.LOCKED}
gui_sg_addsignal -group clkgen_group {{Counters}} -divider
gui_sg_addsignal -group clkgen_group {clkgen_tb.COUNT}
gui_sg_addsignal -group clkgen_group {clkgen_tb.dut.counter}
gui_list_expand -id Wave.1 clkgen_tb.dut.counter
gui_zoom -window Wave.1 -full
