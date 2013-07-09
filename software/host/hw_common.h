/*
 * hw_common.h - Common functionality for talking to the DSi RAM
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

#ifndef __HW_COMMON_H
#define __HW_COMMON_H

#include "fastftdi.h"


/*
 * Hardware configuration registers
 */

#define REG_SYSCLK         0x0000
#define REG_TRACEFLAGS     0x0001
#define REG_POWERFLAGS     0x0002
#define REG_CAM_ADDR_LOW   0x7000
#define REG_CAM_ADDR_HIGH  0x7001
#define REG_CAM_MASK_LOW   0x7002
#define REG_CAM_MASK_HIGH  0x7003
#define REG_CAM_INDEX      0x7004
#define REG_PATCH_OFFSETS  0x7800
#define REG_PATCH_CONTENT  0x8000

#define TRACEFLAG_READS       (1 << 0)
#define TRACEFLAG_WRITES      (1 << 1)

#define POWERFLAG_DSI_RESET    (1 << 0)   // Holding CPU in reset
#define POWERFLAG_DSI_POWERBTN (1 << 1)   // Pressing power button
#define POWERFLAG_DSI_BATT     (1 << 2)   // Battery power supply enable

/*
 * Public
 */

void HW_Init(FTDIDevice *dev, const char *bitstream);
void HW_SetSystemClock(FTDIDevice *dev, float mhz);

void HW_ConfigWriteMultiple(FTDIDevice *dev, uint16_t *addrArray,
                            uint16_t *dataArray, int count, bool async);
void HW_ConfigWrite(FTDIDevice *dev, uint16_t addr, uint16_t data, bool async);

#endif // __HW_COMMON_H
