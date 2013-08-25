/*
 * Main file for 'memhost', the command-line frontend for RAM tracing and patching.
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
#include <string.h>
#include <getopt.h>
#include <unistd.h>
#include <stdbool.h>

#include "fastftdi.h"
#include "hw_common.h"
#include "ftdieep.h"
//#include "hw_trace.h"
//#include "hw_patch.h"

#define CLOCK_FAST               16.756
#define CLOCK_DEFAULT            3.0
#define CLOCK_SLOW               1.0

static void usage(const char *argv0);
typedef unsigned char u8;

// thanks, marcan!
static char ascii(u8 s)
{
  if(s < 0x20) return '.';
  if(s > 0x7E) return '.';
  return s;
}

void hexdump(void *d, int len)
{
  u8 *data;
  int i, off;
  data = (u8 *)d;
  for (off=0; off<len; off += 16) {
    printf("%08x  ",off);
    for(i=0; i<16; i++)
      if((i+off)>=len) printf("   ");
      else printf("%02x ",data[off+i]);

    printf(" ");
    for(i=0; i<16; i++)
      if((i+off)>=len) printf(" ");
      else printf("%c",ascii(data[off+i]));
    printf("\n");
  }
}


static void
usage(const char *argv0)
{
   fprintf(stderr,
           "Usage: %s [options...] [trace file]\n"
           "Command-line frontend for RAM tracing and patching.\n"
           "\n"
           "If a trace file is given, we trace RAM to that file until interrupted\n"
           "by the user. If no trace file is given, the hardware is configured\n"
           "according to the given options, then the tool exits immediately.\n"
           "\n"
           "Options:\n"
           "  -F, --no-fpga-reset   Do not reset the FPGA and the USB interface\n"
           "                          before starting.\n"
           "  -C, --config-only     Exit after loading the FPGA bitstream.\n"
           "  -b, --bitstream=FILE  Load an FPGA bitstream from the provided file.\n"
           "  -S, --stop=COND       Stop when the specified condition (below) is met\n"
           "\n"
           "Stop conditions:\n"
           "  -S time:SECONDS          Stop after SECONDS elapsed on the trace clock.\n"
           "  -S size:MB               Stop after MB megabytes of trace data received.\n"
           "  -S addr:ADDR             Stop when a hexadecimal address is touched.\n"
           "\n"
           "Copyright (C) 2009 Micah Elizabeth Scott <beth@scanlime.org>\n",
           argv0,
           CLOCK_FAST, CLOCK_DEFAULT, CLOCK_SLOW);
   exit(1);
}

int readcb(uint8_t *buffer, int length, FTDIProgressInfo *progress, void *userdata)
{
static unsigned long long bytes_read=0, packets=0;
  if (!length) {
    if (bytes_read > 0) {
      printf("died after %llu bytes (%llu packets)\n", bytes_read, packets);
      bytes_read=0;
      packets=0;
    }
    return 0;
  }
  printf("readcb(%p, %d, %p, %p)\n", buffer, length, progress, userdata);
  if (buffer) hexdump(buffer, length);
  bytes_read += length;
  packets++;
  return 0;
}

int main(int argc, char **argv)
{
   const char *bitstream = NULL;
   const char *tracefile = NULL;
//   HWPatch patch;
   FTDIDevice dev;
   bool resetFPGA = true;
   bool config_only = false;
   bool progeep = false;
   bool eraseeep = false;
   int err, c;

//   HWPatch_Init(&patch);

   while (1) {
      int option_index;
      static struct option long_options[] = {
         {"no-fpga-reset", 0, NULL, 'F'},
         {"config-only", 0, NULL, 'C'},
         {"bitstream", 1, NULL, 'b'},
         {"progEEP", 0, NULL, 'p'},
         {"eraseEEP}", 0, NULL, 'e'},
         {NULL},
      };

      c = getopt_long(argc, argv, "FCb:fsc:pe", long_options, &option_index);
      if (c == -1)
         break;

      switch (c) {

      case 'F':
         resetFPGA = false;
         break;

      case 'C':
         config_only = true;
         break;

      case 'b':
         bitstream = strdup(optarg);
         break;

      case 'p':
         progeep = true;
         break;

      case 'e':
         eraseeep = true;
         break;

      default:
         usage(argv[0]);
      }
   }

   if (optind == argc - 1) {
      // Exactly one extra argument- a trace file
      tracefile = argv[optind];
   } else if (optind < argc) {
      // Too many extra args
      usage(argv[0]);
   }

   err = FTDIDevice_Open(&dev);
   if (err) {
      fprintf(stderr, "USB: Error opening device\n");
      return 1;
   }

  if (eraseeep) {
    FTDIEEP_Erase(&dev);
    FTDIDevice_Reset(&dev);
  }

  if (progeep) {
    FTDIEEP_CheckAndProgram(&dev);
    FTDIDevice_Reset(&dev);
  }


   HW_Init(&dev, resetFPGA ? bitstream : NULL);

   if (config_only) {
      return 0;
   }

   err = FTDIDevice_ReadStream(&dev, FTDI_INTERFACE_A, readcb, NULL, 4, 4);
   printf("ReadStream returned %d\n", err);
   sleep(1);
   FTDIDevice_Close(&dev);

   return 0;
}

