/*
 * iohook_svc.c - Service handlers for the I/O Hook
 *
 * Copyright (C) 2009 Micah Elizabeth Scott
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to
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
* OUT OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

#include "iohook_defs.h"
#include "iohook_svc.h"

#define MIN(a,b)  ((a) > (b) ? (b) : (a))


/*
 * Global Data
 */

static FILE *currentFile;


/*
 * packetString --
 *
 *    A convenience function to convert packet data to a NUL-terminated
 *    string. Uses a static buffer, and requires that the packet
 *    length has already been validated.
 */

const char *
packetString(void *data, uint8_t length)
{
   static char buffer[IOH_DATA_LEN + 1];
   memcpy(buffer, data, length);
   buffer[length] = 0;
   return buffer;
}


/*
 * IOH_HandlePacket --
 *
 *    Entry point for handling I/O hook packets. The packets
 *    have already been validated. To return a response packet,
 *    we return a nonzero length and copy the response data
 *    into 'data'. Responses can be up to IOH_DATA_LEN bytes.
 */

uint8_t
IOH_HandlePacket(FTDIDevice *dev, uint8_t service, void *data, uint8_t length)
{
   switch (service) {
   
   case IOH_SVC_INIT: {
	  HWTrace_HideStatus();
	  fprintf(stderr, "LOG: Inited IOHook sequence.\n");
      return 0;
   }

   case IOH_SVC_LOG_STR: {
      HWTrace_HideStatus();
      fprintf(stderr, "LOG: %s\n", packetString(data, length));
      return 0;
   }

   case IOH_SVC_QUIT: {
      HWTrace_HideStatus();
      fprintf(stderr, "QUIT: %s\n", packetString(data, length));
      exit(1);
      return 0;
   }

   case IOH_SVC_LOG_HEX: {
      int i;
      HWTrace_HideStatus();
      fprintf(stderr, "LOG:");
      if (length & 3) {
         // Byte alignment
         for (i = 0; i < length; i++) {
            fprintf(stderr, " %02x", ((uint8_t*)data)[i]);
         }
      } else {
         // 32-bit alignment
         for (i = 0; i < length/4; i++) {
            fprintf(stderr, " %08x", ((uint32_t*)data)[i]);
         }
      }
      fprintf(stderr, "\n");
      return 0;
   }

   case IOH_SVC_FOPEN_R:
   case IOH_SVC_FOPEN_W: {
      const char *filename = packetString(data, length);
      const char *mode = service == IOH_SVC_FOPEN_W ? "w+" : "r+";
      if (currentFile)
         fclose(currentFile);

      HWTrace_HideStatus();
      fprintf(stderr, "FILE: Opening \"%s\" (%s)\n", filename, mode);
      currentFile = fopen(filename, mode);
      if (!currentFile) {
         perror(filename);
         exit(1);
      }
      return 0;
   }

   case IOH_SVC_FSEEK: {
      uint32_t offset = *(uint32_t*)data;

      if (!currentFile) {
         HWTrace_HideStatus();
         fprintf(stderr, "FILE: Seek attempt with no open file!\n");
         return 0;
      }

      if (fseek(currentFile, offset, SEEK_SET)) {
         HWTrace_HideStatus();
         perror("seek");
         exit(1);
      }
      return 0;
   }

   case IOH_SVC_FREAD: {
      int requested = *(uint32_t*)data;
      int actual;

      if (!currentFile) {
         HWTrace_HideStatus();
         fprintf(stderr, "FILE: Read attempt with no open file!\n");
         return 0;
      }

      actual = fread(data, 1, MIN(requested, IOH_DATA_LEN), currentFile);
      if (requested && actual <= 0) {
         HWTrace_HideStatus();
         perror("fwrite");
         exit(1);
      }
      return actual;
   }

   case IOH_SVC_FWRITE: {
      if (!currentFile) {
         HWTrace_HideStatus();
         fprintf(stderr, "FILE: Write attempt with no open file!\n");
         return 0;
      }

      if (fwrite(data, length, 1, currentFile) != 1) {
         HWTrace_HideStatus();
         perror("fwrite");
         exit(1);
      }
      return 0;
   }

   case IOH_SVC_SETCLOCK: {
      uint32_t khz = *(uint32_t*)data;
      HWTrace_HideStatus();
      HW_SetSystemClock(dev, khz / 1000.0);
      return 0;
   }

   default:
      fprintf(stderr, "IOH: Unknown service 0x%02x\n", service);
   }

   return 0;
}


/*
 * IOH_Exit --
 *
 *    Clean up on exit. This closes the current file, if one is open.
 */

void
IOH_Exit(void)
{
   if (currentFile) {
      fclose(currentFile);
      currentFile = NULL;
   }
}
