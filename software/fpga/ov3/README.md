# Overview

This directory contains the mi

# Build process

Run `make`. 

The output file can be found in build/ov3.fwpkg. The 'fwpkg' file
is a zip archive containing the FPGA bitstream and associated runtime
information. The runtime information includes a register map so the software
tooling can automatically refer to registers by name.

# Files
## ovplatform

Files describing physical hardware, or the parameters of components that may be
found on it.

## ovhw

HDL for the design.

## 3rdparty

Folder for holding 3rd-party non-redistributable IP. The only files that go in here
at the moment are simulation models, IE for SDRAM.

