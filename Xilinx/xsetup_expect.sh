#!/usr/bin/expect -f
# Drives batchxsetup through all Enter-to-continue and EULA prompts.
# batchxsetup is "batch" only in the sense that it takes a config file; it
# still stops on every EULA screen and pages through a lot of text.

set timeout -1
set installer_dir "/tmp/installer"
set installer_root ""

# Locate the extracted installer tree. The tarball name changes across drops
# (e.g. Xilinx_ISE_DS_Lin_14.7_1015_1) so glob for the batch binary instead.
foreach d [glob -nocomplain "$installer_dir/*/bin/lin64/batchxsetup"] {
    set installer_root [file dirname [file dirname [file dirname $d]]]
    break
}
if {$installer_root eq ""} {
    puts stderr "xsetup_expect.sh: could not find batchxsetup under $installer_dir"
    exit 1
}
puts "xsetup_expect.sh: using installer at $installer_root"

spawn "$installer_root/bin/lin64/batchxsetup" --batch /tmp/install_config.txt

expect {
    -re "accept and agree to the terms and conditions above" {
        send "y\r"
        exp_continue
    }
    -re "Press Enter key to continue" {
        send "\r"
        exp_continue
    }
    -re "Installation completed" {
        exp_continue
    }
    timeout {
        puts stderr "xsetup_expect.sh: timeout"
        exit 2
    }
    eof
}

catch wait result
set exit_code [lindex $result 3]
puts "xsetup_expect.sh: batchxsetup exited with code $exit_code"
exit $exit_code
