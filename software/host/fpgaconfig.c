/*
 * fpgaconfig.c - FPGA configuration for a Spartan 6 in Slave SelectMAP (Parallel)
 *                mode over an FT2232H interface.
 *
 * Copyright (C) 2009 Micah Elizabeth Scott
 * Copyright (C) 2013 bushing
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

/* Hardware notes:
 *   Reference: http://www.xilinx.com/support/documentation/user_guides/ug380.pdf
 * 
 *   Pin assignment:
 *
 *    FT2232H     FPGA
 *    --------------------
 *    AD[7:0]     D[7:0]    (configuration, FIFO mode)
 *    AC0/RXF#    p55       (FIFO mode)
 *    AC1/WRSTB#  CCLK      (configuration)
 *    AC2/RD#     p41       (FIFO mode)
 *    AC3/WR#     p40       (FIFO mode)
 *    AC5/CLKOUT  p51       (FIFO mode)
 *    AC6/OE#     p38       (FIFO mode)
 *    BC0         CSI       (configuration)
 *    BC1         RDWR      (configuration)
 *    BC2         DONE      (configuration)
 *    BC3         PROG      (configuration)
 *    BC5         INIT      (configuration)
 *    BC6         M0        (configuration)
 *    BC7         M1        (configuration)
 *
 * The configuration signals could also be used as GPIOs after configuration is complete.
 * CLKOUT should be a 60MHz clock available whenever the host USB is connected (which
 * should be always, in this design).
 * 
 * M[1:0] should be 10 to select Slave SelectMAP mode
 *
 * note: JTAG is also wired up to the second channel of the FT2232H:
 *
 *    FT2232H     FPGA
 *    --------------------
 *    BD0         TCK
 *    BD1         TDI
 *    BD2         TDO
 *    BD3         TMS
 * (Xilinx does not use TRST.)
 *  M[1:0] is ignored when JTAG is used.

 * The remaining FT2232H signals (BC4, BD4, BD5, BD6, BD7) are unused, but wired up to P3.
 */

#include "fpgaconfig.h"
#include "bit_file.h"
#include <unistd.h>
#include <stdio.h>
#include <string.h>

#define CONFIG_BIT_RATE    4000000   // 4 MB/s (mostly arbitrary)

#define FPGA_PART          "6slx9tqg144"

#define PORTB_TCK_BIT      (1 << 0)  // GPIOL0
#define PORTB_TDI_BIT      (1 << 1)  // GPIOL1
#define PORTB_TDO_BIT      (1 << 2)  // GPIOL2
#define PORTB_TMS_BIT      (1 << 3)  // GPIOL3

#define PORTB_CSI_BIT      (1 << 0)  // GPIOH0
#define PORTB_RDWR_BIT     (1 << 1)  // GPIOH1
#define PORTB_DONE_BIT     (1 << 2)  // GPIOH2
#define PORTB_PROG_BIT     (1 << 3)  // GPIOH3
#define PORTB_INIT_BIT     (1 << 5)  // GPIOH5
#define PORTB_M0_BIT       (1 << 6)  // GPIOH6
#define PORTB_M1_BIT       (1 << 7)  // GPIOH7


#define NUM_EXTRA_CLOCKS   512
#define BLOCK_SIZE         (16 * 1024)


static int
ConfigSendBuffer(FTDIDevice *dev, uint8_t *data, size_t length)
{
  /*
   * Send raw configuration data.
   *
   * We're using the slave parallel (SelectMAP) interface, which requires
   * all bits to be swapped. (Why don't they just label the data pins in
   * the opposite order? Beats me...)
   */

  /*
   * This is a clever macro-generated table for reversing bits in a byte,
   * contributed to http://graphics.stanford.edu/~seander/bithacks.html
   * by Hallvard Furuseth.
   */
  static const unsigned char bitReverse[256] = 
    {
#define R2(n)     n,     n + 2*64,     n + 1*64,     n + 3*64
#define R4(n) R2(n), R2(n + 2*16), R2(n + 1*16), R2(n + 3*16)
#define R6(n) R4(n), R4(n + 2*4 ), R4(n + 1*4 ), R4(n + 3*4 )
      R6(0), R6(2), R6(1), R6(3)
    };

  while (length) {
    uint8_t buffer[BLOCK_SIZE];
    size_t chunk = length;
    int i, err;

    if (chunk > BLOCK_SIZE)
      chunk = BLOCK_SIZE;

    for (i = 0; i < chunk; i++)
      buffer[i] = bitReverse[data[i]];

    data += chunk;
    length -= chunk;

    err = FTDIDevice_Write(dev, FTDI_INTERFACE_A, buffer, chunk, false);
    if (err)
      return err;
  }

  return 0;
}


static int
ConfigBegin(FTDIDevice *dev)
{
  int err;
  uint8_t byte;

  /*
   * Reset CLKOUT to its default state (high). This is required prior
   * to FPGA configuration, since the clock input we're using doubles
   * as a configuration mode pin and it must be 1 for the slave
   * parallel mode we're using.
   *
   * This is overkill, but it gets the job done. Some day I'll be
   * bothered to set it explicitly using MPSSE GPIOs commands...
   */

  err = FTDIDevice_Reset(dev);
  if (err)
     return err;

  /*
   * Initialize the FTDI chip using bit-bang and MPSSE mode.
   * Interface A is a byte-wide parallel port for config data, and
   * interface B is GPIO for the control signals.
   */

  err = FTDIDevice_SetMode(dev, FTDI_INTERFACE_A,
			   FTDI_BITMODE_BITBANG, 0xFF,
			   CONFIG_BIT_RATE);
  if (err)
    return err;

  
  /* Enable MPSSE mode */

  err = FTDIDevice_MPSSE_Enable(dev, FTDI_INTERFACE_B); 
  if (err)
    return err;

  // Set speed to 6MHz.
  err = FTDIDevice_MPSSE_SetDivisor(dev, FTDI_INTERFACE_B, 0, 0);
  if (err)
    return err;

  // Set GPIOL pin state / direction
  // 0x08 TCK TDI low, TMS high
  // 0x0B TCK, TDI, TMS output, TDO and GPIOL0-> GPIOL3 input
  err = FTDIDevice_MPSSE_SetLowByte(dev, FTDI_INTERFACE_B, 
    PORTB_TMS_BIT,
    PORTB_TCK_BIT | PORTB_TDI_BIT | PORTB_TMS_BIT);
  if (err)
    return err;

  // Set GPIOH pin state / direction
  err = FTDIDevice_MPSSE_SetHighByte(dev, FTDI_INTERFACE_B, 
    PORTB_CSI_BIT | PORTB_RDWR_BIT | PORTB_PROG_BIT | PORTB_M1_BIT,
    PORTB_CSI_BIT | PORTB_RDWR_BIT | PORTB_PROG_BIT | PORTB_M1_BIT | PORTB_M0_BIT);
  if (err)
    return err;

  /*
   * Begin configuration: Pulse PROG low.
   */

  err = FTDIDevice_MPSSE_SetHighByte(dev, FTDI_INTERFACE_B, 
    PORTB_CSI_BIT | PORTB_RDWR_BIT | PORTB_M1_BIT,
    PORTB_CSI_BIT | PORTB_RDWR_BIT | PORTB_PROG_BIT | PORTB_M1_BIT | PORTB_M0_BIT);
  if (err)
    return err;

  // Into programming mode (CSI/RDWR low, PROG high)
  err = FTDIDevice_MPSSE_SetHighByte(dev, FTDI_INTERFACE_B, 
    PORTB_PROG_BIT | PORTB_M1_BIT,
    PORTB_CSI_BIT | PORTB_RDWR_BIT | PORTB_PROG_BIT | PORTB_M1_BIT | PORTB_M0_BIT);
  if (err)
    return err;

  // Short delay while the FPGA initializes
  usleep(10000);

  fprintf(stderr, "FPGA: sending configuration bitstream\n");

  // Make sure DONE is low now, for sanity.
  err = FTDIDevice_MPSSE_GetHighByte(dev, FTDI_INTERFACE_B, &byte);
  if (err)
    return err;
  if (byte & PORTB_DONE_BIT) {
    fprintf(stderr, "FPGA: DONE pin stuck high? (GPIO=%02x)\n", byte);
    return -1;
  }

  return err;
}


static int
ConfigEnd(FTDIDevice *dev)
{
  int err;
  uint8_t zeroes[NUM_EXTRA_CLOCKS];
  uint8_t byte;

  /*
   * Clock out another block of zeroes, to give the FPGA a chance to
   * finish initializing. This usually isn't required, but the data
   * sheet recommends it as a best practice.
   */

  memset(zeroes, 0, sizeof zeroes);
  err = FTDIDevice_Write(dev, FTDI_INTERFACE_A, zeroes, sizeof zeroes, false);
  if (err)
    return err;

  // Short delay while we wait for DONE to rise
  usleep(10000);

  /*
   * Did configuration succeed? Check the DONE pin.
   */

  err = FTDIDevice_MPSSE_GetHighByte(dev, FTDI_INTERFACE_B, &byte);
  if (err)
    return err;

  if (byte & PORTB_INIT_BIT) {
    fprintf(stderr, "FPGA: CRC OK\n");
  } else {
    fprintf(stderr, "FPGA: CRC failed\n");
    // return -1     (not sure if this will work without a pull-up resistor)
  }

  if (byte & PORTB_DONE_BIT) {
    fprintf(stderr, "FPGA: configured\n");
    return 0;
  } else {
    fprintf(stderr, "FPGA: Configuration error!\n");
    return -1;
  }
}

int FPGA_GetConfigStatus(FTDIDevice * dev)
{
  uint8_t byte;
  int err;
  /*
   * Initialize the FTDI chip using bit-bang and MPSSE mode.
   * Interface A is a byte-wide parallel port for config data, and
   * interface B is GPIO for the control signals.
   */

  err = FTDIDevice_SetMode(dev, FTDI_INTERFACE_A,
			   FTDI_BITMODE_BITBANG, 0xFF,
			   CONFIG_BIT_RATE);
  if (err) {
    fprintf(stderr, "FPGA: GetConfigStatus SetMode (%s)\n", libusb_error_name(err));
    return err;
  }

  
  /* Enable MPSSE mode */

  err = FTDIDevice_MPSSE_Enable(dev, FTDI_INTERFACE_B); 
  if (err) {
    fprintf(stderr, "FPGA: GetConfigStatus MPSSE_Enable (%s)\n", libusb_error_name(err));
    return err;
  }

  // Set GPIOH pin state / direction
  err = FTDIDevice_MPSSE_SetHighByte(dev, FTDI_INTERFACE_B, 
    0,
    0);
  if (err) {
    fprintf(stderr, "FPGA: GetConfigStatus FTDIDevice_MPSSE_SetHighByte (%s)\n", libusb_error_name(err));
    return err;
  }

  do {
    err = FTDIDevice_MPSSE_GetHighByte(dev, FTDI_INTERFACE_B, &byte);
    if (err && err != LIBUSB_ERROR_IO) {
      fprintf(stderr, "FPGA: GetConfigStatus MPSSE_GetHighByte (%s)\n", libusb_error_name(err));
      return err;
    }
  } while (err == LIBUSB_ERROR_IO);

  if (!(byte & PORTB_INIT_BIT)) {
    return -1;
  }

  if (byte & PORTB_DONE_BIT) {
    return 0;
  } else {
    return -1;
  }
}

int
FPGAConfig_LoadFile(FTDIDevice *dev, const char *filename)
{
  int err = 0;
  struct bitfile *bf;

  bf = bitfile_new_from_path(filename);
  if (!bf) {
     perror(filename);
    return -1;
  }

  if (strcmp(bf->part_number, FPGA_PART)) {
    fprintf(stderr, "FPGA: Bitstream has incorrect part number '%s'."
            " Our hardware is '%s'.\n", bf->part_number, FPGA_PART);
    goto done;
  }

  if (bitfile_read_content(bf) <= 0) {
    err = -1;
    goto done;
  }

  fprintf(stderr, "FPGA: Bitstream timestamp %s %s\n", bf->date, bf->time);

  err = ConfigBegin(dev);
  if (err)
    goto done;

  err = ConfigSendBuffer(dev, bf->data, bf->length);
  if (err)
    goto done;

  err = ConfigEnd(dev);
  if (err)
    goto done;

 done:
  bitfile_delete(bf);
  return err;
}
