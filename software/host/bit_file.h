/*
 * bit_file.h - An abstraction for the Xilinx .bit file format,
 *              supports loading the bitstream data itself and
 *              associated metadata from a .bit file.
 *
 *              Thanks to Dave Sullins and his bitinfo utility for
 *              giving a good introduction to the header format.
 *
 * Copyright (C) 2004 Micah Elizabeth Scott
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

#ifndef _H_BIT_FILE
#define _H_BIT_FILE

#include <stdio.h>

struct bitfile {
  /* Only present if the file hasn't been read in completely yet */
  FILE *file;

  /* Metadata */
  char *ncd_filename;
  char *part_number;
  char *date;
  char *time;

  /* The bitstream itself. The length is read at the same time
   * as the rest of the header, but the data itself may be NULL
   * if it hasn't yet been read in.
   */
  int length;
  unsigned char *data;
};

/* Create a bitfile instance from a FILE* or a file name.
 * The FILE* will be closed by the bitfile instance when it's
 * deleted or the content has been read. Returns NULL on error.
 */
struct bitfile*      bitfile_new_from_file     (FILE* f);
struct bitfile*      bitfile_new_from_path     (const char *path);
void                 bitfile_delete            (struct bitfile *self);

/* The bit file's header is read immediately, but content is not read
 * until this function is called. The application may want to skip the
 * file entirely if the metadata reveals problems, or it may want to
 * read the content using an alternative method.
 *
 * After a bit file has been opened, its file pointer will always be
 * pointing to the beginning of the content.
 *
 * Returns the number of bytes read if the entire content was
 * read successfully, or <= 0 on error.
 */
int                  bitfile_read_content      (struct bitfile *self);

#endif /* _H_BIT_FILE */

/* The End */
