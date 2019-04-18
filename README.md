ov_ftdi
=======

This is the main repository of the (FTDI-based) OpenVizsla 3.x USB protocol tracer.

The repository contains

* **hardware** contains the hardware design files (Altium design files, Schematics, PCB layout)
* **software/fpga** contains the source code to the digital logic inside the on-board FPGA
* **software/host** contains the source code to the libusb-based host software
* **software/wireshark** contains some experimental/outdated code for pcap/wireshark integration

Project Status
==============

(as of January 2019):

The hardware design and the FPBA *gateware* are considered stable and reliable,
and have not been touched since late 2014.

The host software is quite basic and just gives you a textual / hex decode of the
USB packets in near real-time.  There is no GUI to visualize and represent the
packets.  There is no code to aggregate packets into transfers.  There's **no
integration with other tools** like [sigrok](https://sigrok.org/), the
[virtual-usb-analyzer](http://vusb-analyzer.sourceforge.net/) or [wireshark](https://wireshark.org/).

At least partly due to the lack of availability of boards, there hasn't been any
progress over the years, particularly not with the original project founder bushing
passing away (see History section below).

We're looking forward to people who'd like to contribute in the area of the host
software.  Integration with sigrok would be nice to show the packet level of USB,
while integration with wireshark would be nice to make use of the various existing
decoders for USB protocols above the transfer level, such as HID, Audio, Mass Storage,
CCID, DFU, etc.


Project History
===============

There was a [Kickstarter
campaign](https://www.kickstarter.com/projects/bushing/openvizsla-open-source-usb-protocol-analyzer) in 2010.  The campaign was hugely successful and interested parties
pledged more than USD 80k towards the development and fist production
batches of the project.  Development happened in 2011 and 2012 on a XMOS
based hardware design (OV2).

Unfortuntely, progress was not as fast as originally anticipated for
a variety of reasons.

By June 2013, bushing decided to go ahead with a much simpler design
based on just a FTDI and FPGA, without the complexity of the XMOS.  This
is what came to be known as OpenVizsla 3 or OV3.  In September 2013,
the digital logic migrated from Verilog to migen (python).

You can find some blog posts by Felix "tmbinc" Dombke related to the
time OV3 was under development at https://debugmo.de/tags/openvizsla/

In July/August 2014, all the backers finally received their boards.

In early 2016, the original creator of OpenVizsla, Ben "bushing" Byer
had unfortunately passed away.  One of the (lesser) consequences of this
was that pre-built/assembled OpenVizsla 3.x boards became unavailable.

As an Open Hardware project, of course anyone could simple build them,
but then if you just need one or a few boards, it's a lot of effort and
not very cost efficient to do so.

In 2018, Harald "LaF0rge" Welte became interested in the project, and
with the help of Felix "tmbinc" Domke, he managed to get hold of the
left-over surplus boards that still existed from bushings' original
production run.  By early 2019 those boards arrived in Germany, from
where they are now being made available via the sysmocom webshop
at https://shop.sysmocom.de/

Hopefully with boards being available again, we can re-spawn some
interest into OpenVizsla, and get some people to work on improving
it, particularly on the host software side for visualization of the
captured data.


Copyright / License
===================

OpenVizsla was originally created by Ben "bushing" Byer and pytey, and
later joined by Felix "tmbinc" Domke.  For detailed copyright statements,
please see the respective documents or code.

The License for the hardware design is the "Creative Commons
Attribution-ShareAlike 3.0 Unported License"

The License for the hardware design is a 2-clause BSD-style license, see
*software/fpga/ov3/LICENSE* for details

The License for the host software is a 2-clause BSD-style license, see
*software/host/LICENSE* for details


Obtaining Hardware
==================

The OpenVizsla 3.2 hardware is finally again available for purchase. This
means you don't have to build your own boards to work with the project.

You can obtain boards from:
* sysmocom, see https://shop.sysmocom.de/
* 3mdeb, visit https://shop.3mdeb.com/

Please note that it is in no way required to buy the boards from mentioned
shops, the design is open hardware and you can just as well build it all by
yourself.
