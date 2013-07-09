/*
 * iohook_defs.h - Definitions for the I/O Hook protocol.
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

#ifndef __IOHOOK_DEFS_H
#define __IOHOOK_DEFS_H

#include <stdint.h>

/*
 * The I/O Hook transmits or receives one 32-byte
 * packet at a time, using a special memory region
 * at IOHOOK_ADDR. This region is observed by the
 * host while parsing memory traces, plus it is
 * patched so that when we read it, we're actually
 * reading a buffer on the FPGA. So reads will not
 * yield the value that was last written.
 *
 * The packet format allows sending or receiving
 * 28 bytes of useful payload at once, with the
 * remaining 32-bit word reserved for identifying
 * the recipient of packets, for including a sequence
 * number that protects against dropped packets and
 * allows polling for new data, and a checksum which
 * protects against bit errors.
 */

#define IOH_ADDR            0x02efffe0
#define IOH_PACKET_LEN      32
#define IOH_DATA_LEN        (IOH_PACKET_LEN - 4)

/*
 * When reading from the host, we always write to memory
 * in units of IOH_DATA_LEN. So in any buffer where alignment
 * can't be guaranteed, extra padding must be added.
*/
#define IOH_PAD8            IOH_DATA_LEN
#define IOH_PAD16           (IOH_DATA_LEN / 2)
#define IOH_PAD32           (IOH_DATA_LEN / 4)

/*
 * Parts of a message footer
 *
 * Notes:
 *   - The sequence number must be in the top 16 bits,
 *     since it must be written last and the memory bus
 *     is 16 bits wide.
 */

#define IOH_SVC_MASK        0xff000000      // Service number
#define IOH_SVC_SHIFT       24
#define IOH_SEQ_MASK        0x00ff0000      // Sequence number
#define IOH_SEQ_SHIFT       16
#define IOH_LEN_MASK        0x0000ff00      // Packet length
#define IOH_LEN_SHIFT       8
#define IOH_CHECK_MASK      0x000000ff      // Check byte
#define IOH_CHECK_SHIFT     0

#define IOH_SVC_LOG_STR     0x01  // Write to log (string)
#define IOH_SVC_LOG_HEX     0x02  // Write to log (hex dump)
#define IOH_SVC_FOPEN_R     0x03  // Open a file for reading. Arg is a filename string.
#define IOH_SVC_FOPEN_W     0x04  // Create/truncate a file. Arg is a filename string.
#define IOH_SVC_FSEEK       0x05  // Seek in current file. Arg = 32-bit offset
#define IOH_SVC_FWRITE      0x06  // Variable length write at current file
#define IOH_SVC_FREAD       0x07  // Read up to IOH_DATA_LEN bytes
#define IOH_SVC_QUIT        0x08  // Tell the host program to exit. Arg = quit message
#define IOH_SVC_SETCLOCK    0x09  // Set sysclock. Arg = 32-bit freq in KHz.
#define IOH_SVC_INIT        0x0A  // Initialize IOHook sequence

/*
 * Check byte format:
 *   - Every 32-bit word is added together using normal 2's complement addition.
 *   - Each 8-bit byte in that word is added.
 */


#endif /* __IOHOOK_DEFS_H */
