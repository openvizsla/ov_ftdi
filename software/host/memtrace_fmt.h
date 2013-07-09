/*
 * memtrace_fmt.h - Definitions and inline functions for dealing with
 *                  the hardware memory tracer's log format.
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

#ifndef __MEMTRACE_FMT_H
#define __MEMTRACE_FMT_H

#include <stdint.h>
#include <stdbool.h>

// Approximate frequency of RAM bus when underclocked.
#define RAM_CLOCK_HZ  4350000

/*
 * Data Types
 */

typedef uint32_t MemPacket;

typedef enum {
   MEMPKT_ADDR = 0,
   MEMPKT_READ,
   MEMPKT_WRITE,
   MEMPKT_TIMESTAMP,
} MemPacketType;

/*
 * Creating a MemPacket from a byte array.
 */

static inline MemPacket
MemPacket_FromBytes(uint8_t *bytes)
{
   /*
    * Reassemble a 32-bit big-endian packet from the bytes. There's a
    * generic C implementation and a faster x86/gcc implementation.
    */
#if defined(__GNUC__) && (defined(__i386__) || defined(__x86_64__))
   uint32_t r = *(uint32_t*)bytes;
   asm ("bswap %0" : "+r" (r));
   return r;
#else
   return (bytes[0] << 24) | (bytes[1] << 16) |
      (bytes[2] << 8) | bytes[3];
#endif
}

/*
 * General packet unpacking
 */

static inline MemPacketType
MemPacket_GetType(MemPacket p)
{
   return (MemPacketType) ((p >> 29) & 0x03);
}

static inline uint32_t
MemPacket_GetPayload(MemPacket p)
{
   return ((p >> 3) & 0x0F) |
          ((p >> 4) & 0x7F0) |
          ((p >> 5) & 0x3F800) |
          ((p >> 6) & 0x7C0000);
}

static inline uint8_t
MemPacket_GetCheck(MemPacket p)
{
   return p & 0x07;
}

/*
 * Packet verification
 */

static inline uint8_t
MemPacket_ComputeCheck(MemPacket p)
{
   uint32_t payload = MemPacket_GetPayload(p);
   return 0x7 & (MemPacket_GetType(p) +
                 (payload & 0x7) +
                 ((payload >> 3) & 0x7) +
                 ((payload >> 6) & 0x7) +
                 ((payload >> 9) & 0x7) +
                 ((payload >> 12) & 0x7) +
                 ((payload >> 15) & 0x7) +
                 ((payload >> 18) & 0x7) +
                 ((payload >> 21) & 0x7));
}

static inline bool
MemPacket_IsChecksumCorrect(MemPacket p)
{
   return MemPacket_ComputeCheck(p) == MemPacket_GetCheck(p);
}

static inline bool
MemPacket_IsAligned(MemPacket p)
{
   return (p & 0x80808080) == 0x80000000;
}

static inline bool
MemPacket_IsOverflow(MemPacket p)
{
   // Signals a hardware buffer overflow. Overflow packets are never aligned.
   return p == 0xFFFFFFFF;
}

/*
 * Unpacking for read/write packets
 */

static inline uint16_t
MemPacket_RW_Word(MemPacket p)
{
   return MemPacket_GetPayload(p) & 0xFFFF;
}

static inline bool
MemPacket_RW_UpperByte(MemPacket p)
{
   return (MemPacket_GetPayload(p) >> 17) & 1;
}

static inline bool
MemPacket_RW_LowerByte(MemPacket p)
{
   return (MemPacket_GetPayload(p) >> 16) & 1;
}

static inline uint32_t
MemPacket_RW_Timestamp(MemPacket p)
{
   return MemPacket_GetPayload(p) >> 18;
}

/*
 * Get the number of clock cycles elapsed prior to any command.
 * Includes the implied single clock cycle of any memory transaction,
 * plus any extra clock cycles encoded in the command itself.
 */

static inline uint32_t
MemPacket_GetDuration(MemPacket p)
{
   switch (MemPacket_GetType(p)) {

   case MEMPKT_ADDR:
      return 1;

   case MEMPKT_READ:
   case MEMPKT_WRITE:
      return 1 + MemPacket_RW_Timestamp(p);

   case MEMPKT_TIMESTAMP:
      return 1 + MemPacket_GetPayload(p);

   }
   return 0;
}


#endif /* __MEMTRACE_FMT_H */
