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
#include "hw_trace.h"
#include "hw_patch.h"

#define DEFAULT_FPGA_BITSTREAM   "stable.bit"
#define CLOCK_FAST               16.756
#define CLOCK_DEFAULT            3.0
#define CLOCK_SLOW               1.0

static void usage(const char *argv0);
static const char *getDefaultBitstreamPath(void);


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
           "                          before starting. Not recommended when tracing,\n"
           "                          but this can be useful for patching or adjusting\n"
           "                          clock frequency without glitches.\n"
           "  -D, --no-dsi-reset    Do not reset the DSi's CPUs when starting a trace.\n"
           "  -b, --bitstream=FILE  Load an FPGA bitstream from the provided file.\n"
           "                          By default, loads \"%s\".\n"
           "  -f, --fast            Run the DSi at full speed (%.3f MHz) instead of\n"
           "                          the default speed of %.3f MHz. Currently\n"
           "                          incompatible with tracing and patching.\n"
           "  -s, --slow            Run the DSi at the lowest speed (%.3f MHz).\n"
           "                          May help prevent buffer overflows.\n"
           "  -c, --clock=MHZ       Set a custom clock frequency, in MHz.\n"
           "  -p, --patch=PATCH     Apply a patch to RAM reads. May be specified\n"
           "                          times. See the accepted PATCH formats below.\n"
           "  -i, --iohook          Enable I/O hooks which allow patches to log data\n"
           "                          to the PC and to read and write data files.\n"
           "  -S, --stop=COND       Stop when the specified condition (below) is met\n"
           "\n"
           "About patch options:\n"
           "  * All addresses are in hexadecimal.\n"
           "  * If a patch affects the first word of a memory burst, the entire burst\n"
           "    will be modified. If the burst is longer than the patch, the data read\n"
           "    is undefined.\n"
           "  * If the first word of a memory burst is not patched, no part of the\n"
           "    burst may be patched.\n"
           "\n"
           "Patch formats:\n"
           "  -p flat:ADDR:FILE        Load a flat binary file at the address ADDR.\n"
           "  -p ascii:ADDR:\"TEXT\"     Write an ASCII string at ADDR.\n"
           "  -p asciiz:ADDR:\"TEXT\"    Write an ASCII string with trailing 0 at ADDR.\n"
           "  -p utf16:ADDR:\"TEXT\"     Write a UTF-16 string at ADDR.\n"
           "  -p utf16z:ADDR:\"TEXT\"    Write a UTF-16 string with trailing 0 at ADDR.\n"
           "  -p hex:ADDR:\"01 23 ...\"  Write a string of hexadecimal bytes at ADDR.\n"
           "                             Whitespace in the string is ignored.\n"
           "  -p elf:FILE              Load each loadable segment from an ELF object.\n"
           "\n"
           "Stop conditions:\n"
           "  -S time:SECONDS          Stop after SECONDS elapsed on the trace clock.\n"
           "  -S size:MB               Stop after MB megabytes of trace data received.\n"
           "  -S addr:ADDR             Stop when a hexadecimal address is touched.\n"
           "\n"
           "Copyright (C) 2009 Micah Elizabeth Scott <beth@scanlime.org>\n",
           argv0,
           DEFAULT_FPGA_BITSTREAM,
           CLOCK_FAST, CLOCK_DEFAULT, CLOCK_SLOW);
   exit(1);
}


int main(int argc, char **argv)
{
   const char *bitstream = getDefaultBitstreamPath();
   const char *tracefile = NULL;
   double clock = CLOCK_DEFAULT;
   HWPatch patch;
   FTDIDevice dev;
   bool resetFPGA = true;
   bool resetDSI = true;
   bool iohook = false;
   int err, c;

   HWPatch_Init(&patch);

   while (1) {
      int option_index;
      static struct option long_options[] = {
         {"no-fpga-reset", 0, NULL, 'F'},
         {"no-dsi-reset", 0, NULL, 'D'},
         {"bitstream", 1, NULL, 'b'},
         {"fast", 0, NULL, 'f'},
         {"slow", 0, NULL, 's'},
         {"clock", 1, NULL, 'c'},
         {"patch", 1, NULL, 'p'},
         {"iohook", 0, NULL, 'i'},
         {"stop", 1, NULL, 'S'},
         {NULL},
      };

      c = getopt_long(argc, argv, "FDb:fsc:p:iS:", long_options, &option_index);
      if (c == -1)
         break;

      switch (c) {

      case 'F':
         resetFPGA = false;
         break;

      case 'D':
         resetDSI = false;
         break;

      case 'b':
         bitstream = strdup(optarg);
         break;

      case 'f':
         clock = CLOCK_FAST;
         break;

      case 's':
         clock = CLOCK_SLOW;
         break;

      case 'c':
         clock = atof(optarg);
         break;

      case 'p':
         HWPatch_ParseString(&patch, optarg);
         break;

      case 'i':
         iohook = true;
         break;

      case 'S':
         HWTrace_ParseStopCondition(optarg);
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

   if (iohook)
      HWTrace_InitIOHookPatch(&patch);

   HW_Init(&dev, resetFPGA ? bitstream : NULL);
   HW_ConfigWrite(&dev, REG_POWERFLAGS, POWERFLAG_DSI_BATT, false);
   HW_SetSystemClock(&dev, clock);
   HW_LoadPatch(&dev, &patch);

   if (tracefile || iohook)
      HW_Trace(&dev, &patch, tracefile, iohook, resetDSI);

   FTDIDevice_Close(&dev);
   IOH_Exit();

   return 0;
}


static const char *
getDefaultBitstreamPath(void)
{
   /*
    * The default bitstream is loaded from the same directory this
    * program is in.  There's no sane way to get this directory
    * portably, and argv[0] is worse than useless. Currently we just
    * use the very Linux-only /proc/self/exe symlink. On other
    * platforms, this should harmlessly fail and search in the current
    * directory only.
    */

   static char buf[PATH_MAX];
   const int basenameMax = sizeof buf - sizeof DEFAULT_FPGA_BITSTREAM - 1;
   ssize_t size;

   size = readlink("/proc/self/exe", buf, basenameMax);
   if (size > 0) {
      char *sep;

      buf[size] = '\0';

      sep = strrchr(buf, '/');

      if (sep) {
         sep[1] = '\0';
      } else {
         buf[0] = '\0';
      }

   } else {
      buf[0] = '\0';
   }

   strcat(buf, DEFAULT_FPGA_BITSTREAM);

   return buf;
}
