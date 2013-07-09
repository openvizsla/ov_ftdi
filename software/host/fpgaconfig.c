/*
 * fpgaconfig.c - FPGA configuration for a Spartan 3E in Slave Parallel mode
 *                over an FT232H interface.
 *
 *   Pin assignment:
 *
 *    FT2232H     FPGA
 *    --------------------
 *    AD[7:0]     D[7:0]
 *    AC1/WRSTB#  CCLK
 *    BD0         CSI
 *    BD1         RDWR
 *    BD2*        DONE
 *    BD3*        PROG
 *
 *    * = Series 330 ohm resistor
 *
 * Copyright (C) 2009 Micah Elizabeth Scott
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

#include "fpgaconfig.h"
#include "bit_file.h"
#include <unistd.h>
#include <stdio.h>
#include <string.h>

#define CONFIG_BIT_RATE    4000000   // 4 MB/s (mostly arbitrary)

#define FPGA_PART          "3s500epq208"

#define PORTB_CSI_BIT      (1 << 0)
#define PORTB_RDWR_BIT     (1 << 1)
#define PORTB_DONE_BIT     (1 << 2)
#define PORTB_PROG_BIT     (1 << 3)

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
   * Initialize the FTDI chip using both interfaces as bit-bang.
   * Interface A is a byte-wide parallel port for config data, and
   * interface B is GPIO for the control signals.
   */

  err = FTDIDevice_SetMode(dev, FTDI_INTERFACE_A,
			   FTDI_BITMODE_BITBANG, 0xFF,
			   CONFIG_BIT_RATE);
  if (err)
    return err;

  err = FTDIDevice_SetMode(dev, FTDI_INTERFACE_B,
			   FTDI_BITMODE_BITBANG,
			   PORTB_CSI_BIT | PORTB_RDWR_BIT | PORTB_PROG_BIT,
			   CONFIG_BIT_RATE);
  if (err)
    return err;

  /*
   * Begin configuration: Pulse PROG low.
   */

  err = FTDIDevice_WriteByteSync(dev, FTDI_INTERFACE_B,
				 PORTB_CSI_BIT | PORTB_RDWR_BIT | PORTB_PROG_BIT);
  if (err)
    return err;

  err = FTDIDevice_WriteByteSync(dev, FTDI_INTERFACE_B,
				 PORTB_CSI_BIT | PORTB_RDWR_BIT);
  if (err)
    return err;

  // Into programming mode (CSI/RDWR low, PROG high)
  err = FTDIDevice_WriteByteSync(dev, FTDI_INTERFACE_B, PORTB_PROG_BIT);
  if (err)
    return err;

  // Short delay while the FPGA initializes
  usleep(10000);

  fprintf(stderr, "FPGA: sending configuration bitstream\n");

  // Make sure DONE is low now, for sanity.
  err = FTDIDevice_ReadByteSync(dev, FTDI_INTERFACE_B, &byte);
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

  /*
   * Did configuration succeed? Check the DONE pin.
   */

  err = FTDIDevice_ReadByteSync(dev, FTDI_INTERFACE_B, &byte);
  if (err)
    return err;

  if (byte & PORTB_DONE_BIT) {
    fprintf(stderr, "FPGA: configured\n");
    return 0;
  } else {
    fprintf(stderr, "FPGA: Configuration error!\n");
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
