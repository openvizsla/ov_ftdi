/*
 * bit_file.c - An abstraction for the Xilinx .bit file format,
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

#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include "bit_file.h"

/* Returns the number of fields read successfully, or -1 on error */
static int           bitfile_read_header       (struct bitfile *self);

/* Handle one header field. The type code has already been read, but none
 * of the field's content. Returns 0 on success, 1 on end-of-header.
 */
static int           bitfile_handle_hdr_field  (struct bitfile *self, unsigned char type);

/* Portable big-endian unsigned integer reading, returns -1 on error. */
static int           bitfile_read_int          (struct bitfile *self, int bytes);

/* Read a counted string from the current position in the bitfile. Returns
 * a freshly allocated pointer, or NULL on error.
 */
static char*         bitfile_read_string       (struct bitfile *self);

/*********************************************************************/


static int bitfile_read_header(struct bitfile *self)
{
  static const unsigned char ref_magic[] = {0x00, 0x09, 0x0F, 0xF0,
					    0x0F, 0xF0, 0x0F, 0xF0,
					    0x0F, 0xF0, 0x00, 0x00,
					    0x01};
  unsigned char file_magic[sizeof(ref_magic)];
  int code;
  int n_fields;

  /* The file begins with a 13-byte magic number identifying it as a BIT file */
  if (fread(file_magic, sizeof(ref_magic), 1, self->file) < 1)
    return -1;
  if (memcmp(file_magic, ref_magic, sizeof(ref_magic)))
    return -1;

  /* Every other section is identified by a type character */
  n_fields = 0;
  while ((code = fgetc(self->file)) != EOF) {
    n_fields++;
    if (bitfile_handle_hdr_field(self, (unsigned char) code))
      break;
  }
  return n_fields;
}

static int bitfile_handle_hdr_field(struct bitfile *self, unsigned char type)
{
  switch (type) {

    /* Metadata strings */

  case 'a':
    self->ncd_filename = bitfile_read_string(self);
    break;

  case 'b':
    self->part_number = bitfile_read_string(self);
    break;

  case 'c':
    self->date = bitfile_read_string(self);
    break;

  case 'd':
    self->time = bitfile_read_string(self);
    break;

    /* Marks the end of the header, and holds the bitstream size */

  case 'e':
    self->length = bitfile_read_int(self, 4);
    return 1;

  }
  return 0;
}

static int bitfile_read_int(struct bitfile *self, int bytes)
{
  int byte, word, i;

  word = 0;
  for (i=0; i<bytes; i++) {
    word <<= 8;
    byte = fgetc(self->file);
    if (byte == EOF)
      return -1;
    word |= byte;
  }
  return word;
}

static char* bitfile_read_string(struct bitfile *self)
{
  int length;
  char *str;

  length = bitfile_read_int(self, 2);
  if (length < 0)
    return NULL;

  /* The string on disk should be nul-terminated, but don't count on it */
  str = malloc(length + 1);
  if (!str)
    return NULL;
  str[length] = '\0';

  if (fread(str, length, 1, self->file) < 1) {
    free(str);
    return NULL;
  }

  return str;
}

struct bitfile* bitfile_new_from_file(FILE* f)
{
  struct bitfile *self;

  self = malloc(sizeof(struct bitfile));
  if (!self)
    return NULL;
  memset(self, 0, sizeof(struct bitfile));

  self->file = f;
  if (bitfile_read_header(self) < 0) {
    bitfile_delete(self);
    return NULL;
  }
  return self;
}

struct bitfile* bitfile_new_from_path(const char *path)
{
  FILE *f = fopen(path, "rb");
  if (!f)
    return NULL;
  return bitfile_new_from_file(f);
}

void bitfile_delete(struct bitfile *self)
{
  if (self->file)
    fclose(self->file);
  if (self->data)
    free(self->data);
  if (self->ncd_filename)
    free(self->ncd_filename);
  if (self->part_number)
    free(self->part_number);
  if (self->date)
    free(self->date);
  if (self->time)
    free(self->time);
  free(self);
}

int bitfile_read_content(struct bitfile *self)
{
  if (self->data)
    return -1;
  if (!self->file)
    return -1;

  self->data = malloc(self->length);
  if (!self->data)
    return -1;
  if (fread(self->data, self->length, 1, self->file) < 1)
    return -1;

  fclose(self->file);
  self->file = NULL;

  return self->length;
}

/* The End */
