/*
 * hw_common.c - Common functionality for talking to the DSi RAM
 *               tracing/injecting hardware over USB.
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

#include <stdio.h>
#include <stdlib.h>

#include "hw_common.h"
#include "fpgaconfig.h"

/*
 * HW_Init --
 *
 *    One-time initialization for the hardware.
 *    'bitstream' is optional. If non-NULL, the FPGA is reconfigured.
 */

void
HW_Init(FTDIDevice *dev, const char *bitstream)
{
   int err;

   if (bitstream) {
      err = FPGAConfig_LoadFile(dev, bitstream);
      if (err)
         exit(1);
   }

   err = FTDIDevice_SetMode(dev, FTDI_INTERFACE_A,
                            FTDI_BITMODE_SYNC_FIFO, 0xFF, 0);
   if (err)
      exit(1);
}


#if 0
/*
 * HW_SetSystemClock --
 *
 *    Set the system clock to an approximation of the given frequency, in MHz.
 *    We'll display a message with the actual frequency being set.
 */

void
HW_SetSystemClock(FTDIDevice *dev, float mhz)
{
   const double synthStep = 200.0 / 0x80000;
   int regValue = (mhz / synthStep) + 0.5;
   double actual = regValue * synthStep;

   if (regValue > 0xffff)
      regValue = 0xffff;

   fprintf(stderr, "CLOCK: Setting system clock to %.06f MHz (0x%04x)\n",
           actual, regValue);

   HW_ConfigWrite(dev, REG_SYSCLK, regValue, true);
}
#endif

/*
 * HW_ConfigWriteMultiple --
 *
 *    Write any number of register address/value pairs to the hardware.
 *    This is more efficient than many separate ConfigWrite()s, since it
 *    can send all registers in a single USB transfer.
 */

void
HW_ConfigWriteMultiple(FTDIDevice *dev, uint16_t *addrArray,
                       uint16_t *dataArray, int count, bool async)
{
   /*
    * Config writes are 5 bytes long, but pad them to 8 bytes.
    * This means we have a nice round number of them in each USB
    * packet.
    *
    * XXX: Also, this is a workaround for a hardware bug. Either the
    *      FT2232H or the FPGA seem to eat the first byte of a USB packet
    *      sometimes.
    */
   const int writeSize = 8;
   const int writeOffset = 1;

   uint8_t *buffer;
   uint32_t bufferSize = count * writeSize;
   uint8_t *packet;

   buffer = calloc(1, bufferSize);
   if (!buffer) {
      perror("Error allocating config write buffer");
      exit(1);
   }

   packet = buffer + writeOffset;

   while (count) {
      uint16_t addr = *addrArray;
      uint16_t data = *dataArray;

      addrArray++;
      dataArray++;
      count--;

      // Pack the data as described in usb_comm.v
      packet[0] = 0x80 | ((addr & 0xC000) >> 12) | ((data & 0xC000) >> 14);
      packet[1] = (addr & 0x3F80) >> 7;
      packet[2] = addr & 0x007F;
      packet[3] = (data & 0x3F80) >> 7;
      packet[4] = data & 0x007F;

      packet += writeSize;
   }

   if (FTDIDevice_Write(dev, FTDI_INTERFACE_A, buffer, bufferSize, async)) {
      perror("Error writing configuration registers");
      exit(1);
   }

   free(buffer);
}


/*
 * HW_ConfigWrite --
 *
 *    Write a 16-bit value to one of the hardware's configuration
 *    registers.
 *
 *    Write to a configuration register on the FPGA. These
 *    registers are used for global settings and for storing
 *    RAM patches. Registers are 16 bits wide, and they exist
 *    in a 16-bit virtual address space.
 *
 *    This is actually just a convenience wrapper around
 *    HW_ConfigWriteMultiple().
 */

void
HW_ConfigWrite(FTDIDevice *dev, uint16_t addr, uint16_t data, bool async)
{
   HW_ConfigWriteMultiple(dev, &addr, &data, 1, async);
}
