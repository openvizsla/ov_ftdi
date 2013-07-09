/*
 * hw_patch.c - Client program for the RAM patching hardware.
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
#include <assert.h>

#include "elf.h"
#include "hw_patch.h"


/*
 * HWPatch_Init --
 *
 *    Initialize a patch to its default state. All registers will
 *    have dummy values.
 */

void
HWPatch_Init(HWPatch *patch)
{
   int i;

   memset(patch, 0, sizeof *patch);

   /*
    * Set all patches addresses to all ones.
    *
    * XXX: Right now the hardware will actually interpret this
    *      as a patch to the last word of memory, but in the future
    *      we might make this value special.
    */
   for (i = 0; i < PATCH_NUM_BLOCKS; i++) {
      patch->camAddrs[i] = 0xFFFFFFFF;
   }
}


/*
 * HWPatch_AllocRegion --
 *
 *    Allocate a contiguous regions of bytes in a HWPatch, splitting the region
 *    into as many CAM blocks as necessary. Returns a pointer where 'size' bytes
 *    of content may be written.
 *
 *    'size' will be automatically rounded up to a multiple of 2 bytes.
 */

uint8_t *
HWPatch_AllocRegion(HWPatch *patch, uint32_t baseAddr, uint32_t size)
{
   int contentBase;
   uint8_t *contentPtr;
   uint16_t blockOffset;

   /*
    * Allocate a new contiguous block of content memory
    */

   size = (size + 1) & ~1;
   assert((patch->contentSize & 1) == 0);
   contentBase = patch->contentSize;
   blockOffset = (uint16_t) ((contentBase - baseAddr) >> 1);
   patch->contentSize += size;

   if (patch->contentSize > PATCH_CONTENT_SIZE) {
      fprintf(stderr, "PATCH: Out of space for content (Allocated %d of %d bytes)\n",
              patch->contentSize, PATCH_CONTENT_SIZE);
      exit(1);
   }

   /*
    * Iteratively emit new patch blocks. For each block, find the
    * largest power of two that will fit our constraints, then
    * move on to the next portion of the patch region.
    *
    * Each block must be:
    *   - A power of two in size
    *   - Aligned on a multiple of its size
    *   - Contained within the allocated patch region
    */

   while (size) {
      uint32_t blockMask = 0x7fffffff;

      if (patch->numBlocks >= PATCH_NUM_BLOCKS) {
         fprintf(stderr, "PATCH: Out of blocks (patch region too complex)\n");
         exit(1);
      }

      while (blockMask >= size || (blockMask & baseAddr)) {
         assert(blockMask != 0);
         blockMask >>= 1;
      }

      fprintf(stderr, "PATCH: Block at %08x mask=%08x offset=%04x\n",
              baseAddr, blockMask, blockOffset);

      patch->camAddrs[patch->numBlocks] = baseAddr >> 1;
      patch->camMasks[patch->numBlocks] = blockMask >> 1;
      patch->blockOffsets[patch->numBlocks] = blockOffset;

      baseAddr += blockMask + 1;
      size -= blockMask + 1;
      patch->numBlocks++;
   }

   return patch->content + contentBase;
}


/*
 * patchContentWord --
 *
 *    Inline function to retrieve one word from a patch's content buffer.
 */

static inline uint16_t
patchContentWord(HWPatch *patch, int i)
{
   return patch->content[i << 1] + (patch->content[1 + (i << 1)] << 8);
}


/*
 * HWPatch_Load --
 *
 *    Load the contents of a HWPatch into the hardware.
 *
 *    This loads the patch content, patch offsets, and
 *    CAM (Content Addressable Memory) in that order.
 */

void
HW_LoadPatch(FTDIDevice *dev, HWPatch *patch)
{
   const int numRegs = (PATCH_NUM_BLOCKS * 5 +    // CAM registers
                        PATCH_NUM_BLOCKS +        // Offset registers
                        PATCH_CONTENT_SIZE / 2);  // Content memory;
   uint16_t regAddr[numRegs];
   uint16_t regData[numRegs];
   int i, reg = 0;

   fprintf(stderr, "PATCH: Loading hardware with %d block%s, %d bytes of content\n",
           patch->numBlocks, patch->numBlocks == 1 ? "" : "s", patch->contentSize);

   for (i = 0; i < PATCH_CONTENT_SIZE/2; i++) {
      regAddr[reg] = REG_PATCH_CONTENT + i;
      regData[reg] = patchContentWord(patch, i);
      reg++;
   }

   for (i = 0; i < PATCH_NUM_BLOCKS; i++) {
      regAddr[reg] = REG_PATCH_OFFSETS + i;
      regData[reg] = patch->blockOffsets[i];
      reg++;
   }

   for (i = 0; i < PATCH_NUM_BLOCKS; i++) {
      regAddr[reg] = REG_CAM_ADDR_LOW;
      regData[reg] = patch->camAddrs[i];
      reg++;

      regAddr[reg] = REG_CAM_ADDR_HIGH;
      regData[reg] = patch->camAddrs[i] >> 16;
      reg++;

      regAddr[reg] = REG_CAM_MASK_LOW;
      regData[reg] = patch->camMasks[i];
      reg++;

      regAddr[reg] = REG_CAM_MASK_HIGH;
      regData[reg] = patch->camMasks[i] >> 16;
      reg++;

      regAddr[reg] = REG_CAM_INDEX;
      regData[reg] = i;
      reg++;
   }

   assert(reg == numRegs);
   HW_ConfigWriteMultiple(dev, regAddr, regData, numRegs, false);
}


/*
 * HW_UpdatePatchRegion --
 *
 *    Send updated contents into the hardware for part of an HWPatch.
 *    'buf' can be any word-aligned pointer in a buffer returned
 *    by a previous call to HWPatch_AllocRegion for this patch.
 *
 *    Each 16-bit word in the region will be written in order.
 *    16-bit words are atomic, but the write as a whole isn't.
 *
 *    The new patch takes effect asynchronously.
 */

void
HW_UpdatePatchRegion(FTDIDevice *dev, HWPatch *patch,
                     uint8_t *buf, uint32_t size)
{
   uint16_t regAddr[PATCH_CONTENT_SIZE / 2];
   uint16_t regData[PATCH_CONTENT_SIZE / 2];
   uint32_t offset = buf - patch->content;
   int i, numWords, wordOffset;

   assert(offset < PATCH_CONTENT_SIZE);
   assert((offset & 1) == 0);

   // Round size up to a whole word
   wordOffset = offset >> 1;
   numWords = (size + 1) >> 1;

   for (i = 0; i < numWords; i++) {
      regAddr[i] = REG_PATCH_CONTENT + i + wordOffset;
      regData[i] = patchContentWord(patch, i + wordOffset);
   }

   HW_ConfigWriteMultiple(dev, regAddr, regData, numWords, true);
}


/*
 * HWPatch_ParseString --
 *
 *    Parse a patch specification in one of the formats accepted by
 *    our command line interface, and load the patch.
 */

void
HWPatch_ParseString(HWPatch *patch, const char *patchString)
{
   char *tokSave;
   char *str = strdup(patchString);
   char *delim1 = strchr(str, ':');
   char *delim2 = delim1 ? strchr(delim1 + 1, ':') : NULL;

   if (delim1) {
      unsigned long addr;

      *delim1 = '\0';
      if (delim2) {
         *delim2 = '\0';
         addr = strtoul(delim1 + 1, NULL, 16);
      }

      if (!strcmp(str, "flat") && delim2) {
         HWPatch_LoadFlat(patch, addr, delim2 + 1);
         goto done;
      }

      if (!strcmp(str, "ascii") && delim2) {
         char *string = delim2 + 1;
         HWPatch_LoadString(patch, addr, string, strlen(string));
         goto done;
      }

      if (!strcmp(str, "asciiz") && delim2) {
         char *string = delim2 + 1;
         HWPatch_LoadString(patch, addr, string, strlen(string) + 1);
         goto done;
      }

      if (!strcmp(str, "utf16") && delim2) {
         char *string = delim2 + 1;
         HWPatch_LoadStringUTF16(patch, addr, string, strlen(string));
         goto done;
      }

      if (!strcmp(str, "utf16z") && delim2) {
         char *string = delim2 + 1;
         HWPatch_LoadStringUTF16(patch, addr, string, strlen(string) + 1);
         goto done;
      }

      if (!strcmp(str, "hex") && delim2) {
         HWPatch_LoadHex(patch, addr, delim2 + 1);
         goto done;
      }

      if (!strcmp(str, "elf")) {
         HWPatch_LoadELF(patch, delim1 + 1);
         goto done;
      }
   }

   fprintf(stderr, "Can't parse patch string \"%s\".\n", patchString);
   exit(1);

 done:
   free(str);
}


void
HWPatch_LoadFlat(HWPatch *patch, uint32_t addr, const char *fileName)
{
   FILE *f = fopen(fileName, "rb");
   uint8_t *buffer;
   int length;

   if (!f) {
      perror(fileName);
      exit(1);
   }

   fseek(f, 0, SEEK_END);
   length = ftell(f);
   fseek(f, 0, SEEK_SET);

   buffer = HWPatch_AllocRegion(patch, addr, length);

   if (fread(buffer, length, 1, f) != 1) {
      perror("Error reading patch file");
      exit(1);
   }

   fclose(f);
}


void
HWPatch_LoadString(HWPatch *patch, uint32_t addr,
                   const char *string, int length)
{
   memcpy(HWPatch_AllocRegion(patch, addr, length),
          string, length);
}


void
HWPatch_LoadStringUTF16(HWPatch *patch, uint32_t addr,
                        const char *string, int length)
{
   uint8_t *wide = HWPatch_AllocRegion(patch, addr, length << 1);

   while (length--) {
      wide[0] = *(string++);
      wide[1] = 0;
      wide += 2;
   }
}


/*
 * parseHex --
 *
 *    Convert hex to binary, ignoring whitespace. If buffer==NULL,
 *    calculates length only. Exits on error.
 */

static int
parseHex(const char *string, uint8_t *buffer)
{
   int length = 0;
   char c;
   uint8_t byte = 0;
   int nybble = 0;

   while ((c = *string)) {
      if (!isblank(c)) {
         c = tolower(c);

         byte <<= 4;

         if (c >= '0' && c <= '9')
            byte |= c - '0';
         else if (c >= 'a' && c <= 'f')
            byte |= c - 'a' + 10;
         else {
            fprintf(stderr, "Error: Illegal byte in hexadecimal patch: '%c'\n", c);
            exit(1);
         }

         if (nybble) {
            if (buffer)
               *(buffer++) = byte;
            length++;
         }
         nybble = !nybble;
      }
      string++;
   }
   if (nybble) {
      fprintf(stderr, "Error: Hexadecimal patch has odd length!\n");
      exit(1);
   }

   return length;
}


void
HWPatch_LoadHex(HWPatch *patch, uint32_t addr, const char *string)
{
   int length = parseHex(string, NULL);
   parseHex(string, HWPatch_AllocRegion(patch, addr, length));
}


/*
 * HWPatch_LoadELF --
 *
 *    Load all segments from an ELF32 file.
 *    Assumes both this machine and the ELF file are little-endian.
 */

void
HWPatch_LoadELF(HWPatch *patch, const char *fileName)
{
   FILE *f = fopen(fileName, "rb");
   Elf32_Ehdr ehdr;
   int phOffset;
   int i;

   if (!f) {
      perror(fileName);
      exit(1);
   }

   /*
    * Read the ELF header
    */

   if (fread(&ehdr, sizeof ehdr, 1, f) != 1) {
      perror("ELF: Error reading ELF header");
      exit(1);
   }

   if (ehdr.e_ident[EI_MAG0] != ELFMAG0 ||
       ehdr.e_ident[EI_MAG1] != ELFMAG1 ||
       ehdr.e_ident[EI_MAG2] != ELFMAG2 ||
       ehdr.e_ident[EI_MAG3] != ELFMAG3) {
      fprintf(stderr, "ELF: Bad magic, not an ELF file?\n");
      exit(1);
   }

   if (ehdr.e_ident[EI_CLASS] != ELFCLASS32 ||
       ehdr.e_ident[EI_DATA] != ELFDATA2LSB) {
      fprintf(stderr, "ELF: Not a 32-bit little-endian ELF file\n");
      exit(1);
   }

   if (ehdr.e_ident[EI_VERSION] != EV_CURRENT) {
      fprintf(stderr, "ELF: Bad ELF version (%d)\n", ehdr.e_ident[EI_VERSION]);
      exit(1);
   }

   /*
    * Read the program header
    */

   phOffset = ehdr.e_phoff;
   for (i = 0; i < ehdr.e_phnum; i++) {
      Elf32_Phdr phdr;

      fseek(f, phOffset, SEEK_SET);
      phOffset += ehdr.e_phentsize;
      if (fread(&phdr, sizeof phdr, 1, f) != 1) {
         perror("ELF: Error reading program header");
         exit(1);
      }

      // We only care about loadable segments
      if (phdr.p_type == PT_LOAD) {
         // Use the physical address
         uint32_t addr = phdr.p_paddr;
         uint8_t *buffer;

         fprintf(stderr, "ELF: Segment at %08x %c%c%c memsz=%d filesz=%d\n",
                 addr,
                 phdr.p_flags & PF_R ? 'r' : '-',
                 phdr.p_flags & PF_W ? 'w' : '-',
                 phdr.p_flags & PF_X ? 'x' : '-',
                 phdr.p_memsz, phdr.p_filesz);

         if (phdr.p_filesz > phdr.p_memsz) {
            fprintf(stderr, "ELF: Error, file size greater than memory size\n");
            exit(1);
         }

         // Examine read/write flags:
         switch (phdr.p_flags & (PF_R | PF_W)) {

         case PF_R:  // Read-only. We can patch this.
            buffer = HWPatch_AllocRegion(patch, addr, phdr.p_memsz);
            if (phdr.p_filesz > 0) {
               fseek(f, phdr.p_offset, SEEK_SET);
               if (fread(buffer, phdr.p_filesz, 1, f) != 1) {
                  perror("ELF: Error reading segment data");
                  exit(1);
               }
            }
            break;

         case 0:     // No-access. This is a dummy segment, ignore it.
            break;

         default:    // Other. Not allowed- patched memory is read-only.
            fprintf(stderr, "ELF: Patched segments must be read-only or no-access.\n");
            exit(1);
            break;
         }
      }
   }

   fclose(f);
}
