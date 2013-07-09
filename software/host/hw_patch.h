/*
 * hw_patch.h - Client program for the RAM patching hardware.
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

#ifndef __HW_PATCH_H
#define __HW_PATCH_H

#include <stdint.h>
#include "hw_common.h"


#define PATCH_CONTENT_SIZE  (16 * 1024)
#define PATCH_CONTENT_WORDS (PATCH_CONTENT_SIZE >> 1)
#define PATCH_NUM_BLOCKS    64


/*
 * HWPatch -- A container for the entire state of the hardware patching engine,
 *            plus some metadata that we use for allocating patch memory.
 */

typedef struct {
   // Hardware data.
   uint32_t camAddrs[PATCH_NUM_BLOCKS];
   uint32_t camMasks[PATCH_NUM_BLOCKS];
   uint16_t blockOffsets[PATCH_NUM_BLOCKS];
   uint8_t  content[PATCH_CONTENT_SIZE];

   // Amount of allocated space
   int numBlocks;
   int contentSize;
} HWPatch;


/*
 * Public functions
 */

void HWPatch_Init(HWPatch *patch);
uint8_t *HWPatch_AllocRegion(HWPatch *patch, uint32_t baseAddr, uint32_t size);

void HWPatch_ParseString(HWPatch *patch, const char *str);
void HWPatch_LoadFlat(HWPatch *patch, uint32_t addr, const char *fileName);
void HWPatch_LoadELF(HWPatch *patch, const char *fileName);
void HWPatch_LoadString(HWPatch *patch, uint32_t addr,
                        const char *string, int length);
void HWPatch_LoadStringUTF16(HWPatch *patch, uint32_t addr,
                             const char *string, int length);
void HWPatch_LoadHex(HWPatch *patch, uint32_t addr, const char *string);

void HW_LoadPatch(FTDIDevice *dev, HWPatch *patch);
void HW_UpdatePatchRegion(FTDIDevice *dev, HWPatch *patch,
                          uint8_t *buf, uint32_t size);


#endif // __HW_PATCH_H
