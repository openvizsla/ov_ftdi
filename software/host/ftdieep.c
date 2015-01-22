/*
 * ftdieep.h - Support for generating EEPROM information for the FT2232H,
 *             using the 93LC46 EEPROM (93LC56 and 93LC66 not supported).
 *
 * Copyright (C) 2010 Hector Martin <hector@marcansoft.com>
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


#include "ftdieep.h"
#include <stdio.h>
#include <string.h>
#include <time.h>

#define FTDI_READ_EEPROM_REQUEST      0x90
#define FTDI_WRITE_EEPROM_REQUEST     0x91

enum EEPIndex {
	EEP_MODES = 0x00,
	EEP_IDVENDOR,
	EEP_IDPRODUCT,
	EEP_UNKNOWN1,
	EEP_USBCFG1,
	EEP_USBCFG2,
	EEP_PORTCFG,
	EEP_MANUFACTURER,
	EEP_PRODUCT,
	EEP_SERIAL,
	/* 0x0a, 0x0b */
	EEP_EEPTYPE = 0x0c,
	EEP_STRINGSTART,
	/* strings: 0x0d - 0x3e */

	EEP_CHECKSUM = 0x3f,
	EEP_SIZE = 0x40
};

#define EEP_MODES_SET(a,b) ( (a) | ((b)<<8) )

#define EEP_UART    0x00
#define EEP_245FIFO 0x01
#define EEP_CPUFIFO 0x02
#define EEP_OPTO    0x04
#define EEP_D2XX    0x00
#define EEP_VCP     0x08

#define EEP_MODE_SUSPEND_DBUS7 0x8000

#define EEP_UNKNOWN1_VALUE 0x700

#define EEP_USBCFG1_BASE         0x80
#define EEP_USBCFG1_REMOTEWAKEUP 0x20
#define EEP_USBCFG1_BUSPOWERED   0x00
#define EEP_USBCFG1_SELFPOWERED  0x40
#define EEP_USBCFG1_MAXPOWER(x)  ( ((x)/2) << 8 )

#define EEP_USBCFG2_IOPULLDOWN   0x04
#define EEP_USBCFG2_NOSERIAL     0x00
#define EEP_USBCFG2_HAVESERIAL   0x08

#define EEP_PORTCFG_SET(al,ah,bl,bh) ( (al) | ((ah)<<4) | ((bl) << 8) | ((bh) << 12) )

#define EEP_4MA      0x0
#define EEP_8MA      0x1
#define EEP_12MA     0x2
#define EEP_16MA     0x3
#define EEP_SLOWSLEW 0x4
#define EEP_SCHMITT  0x8

#define EEP_EEPTYPE_93LC46 0x46

#define USB_STRING_DESCRIPTOR 3

static int FTDIEEP_WriteWord(FTDIDevice *dev, uint8_t addr, uint16_t data)
{
	int err;

	err = libusb_control_transfer(dev->handle,
	                              LIBUSB_REQUEST_TYPE_VENDOR
	                              | LIBUSB_RECIPIENT_DEVICE
	                              | LIBUSB_ENDPOINT_OUT,
	                              FTDI_WRITE_EEPROM_REQUEST,
	                              data,
	                              addr,
	                              NULL, 0,
	                              FTDI_COMMAND_TIMEOUT);
	return 0;
}

static int FTDIEEP_ReadWord(FTDIDevice *dev, uint8_t addr, uint16_t *data)
{
	int err;
	uint8_t buf[2];

	err = libusb_control_transfer(dev->handle,
	                              LIBUSB_REQUEST_TYPE_VENDOR
	                              | LIBUSB_RECIPIENT_DEVICE
	                              | LIBUSB_ENDPOINT_IN,
	                              FTDI_READ_EEPROM_REQUEST,
	                              0,
	                              addr,
	                              buf, sizeof(uint16_t),
	                              FTDI_COMMAND_TIMEOUT);
	if (err < 0)
		return err;
	if (err != 2)
		return -1;
	*data = (buf[1]<<8) | buf[0];
	return 0;
}

static int FTDIEEP_MakeStringDescriptor(uint16_t *data, uint8_t id, uint8_t *addr, const char *str)
{
	int len;

	/*
	   NOTE: Looks like the only thing that needs to change for C56 and C66 is this part.
	   Something about strings starting at offset 0x40+EEP_STRINGSTART instead,
	   and removing the 0x0080 below, but the original code is weird and inconsistent.
	*/

	len = strlen(str);
	if ((*addr + 2*len + 2) > EEP_CHECKSUM) {
		fprintf(stderr, "EEPROM: String does not fit in EEPROM\n");
		return -1;
	}

	data[id] = 0x0080 | (*addr*2) | ((2*len + 2) << 8);

	data[(*addr)++] = (2*len + 2) | (USB_STRING_DESCRIPTOR<<8);
	while (len--) {
		data[(*addr)++] = *str++;
	}

	return 0;
}

static void FTDIEEP_GenerateSerial(char *serial, unsigned int number)
{
	snprintf(serial, 9, "OV%06u", number);
}

static int FTDIEEP_WriteDefaults(FTDIDevice *dev, unsigned int number)
{
	int err;
	uint16_t data[EEP_SIZE];
	char serial[16];
	uint8_t addr;
	uint16_t check = 0xaaaa;

	memset(data, 0, sizeof(data));

	data[EEP_MODES] = EEP_MODES_SET(
	                   /* PORT A */ EEP_245FIFO | EEP_D2XX,
	                   /* PORT B */ EEP_245FIFO | EEP_D2XX );
	data[EEP_IDVENDOR] = OV_VENDOR;
	data[EEP_IDPRODUCT] = OV_PRODUCT;
	data[EEP_UNKNOWN1] = EEP_UNKNOWN1_VALUE;
	data[EEP_USBCFG1] = EEP_USBCFG1_BASE |
	                    EEP_USBCFG1_BUSPOWERED |
	                    EEP_USBCFG1_MAXPOWER(500);
	data[EEP_USBCFG2] = EEP_USBCFG2_HAVESERIAL;
	data[EEP_PORTCFG] = EEP_PORTCFG_SET(
	                      /* PORT AL */ EEP_8MA,
	                      /* PORT AH */ EEP_8MA,
	                      /* PORT BL */ EEP_8MA,
	                      /* PORT BH */ EEP_8MA );
	data[EEP_EEPTYPE] = EEP_EEPTYPE_93LC46;

	addr = EEP_STRINGSTART;

	FTDIEEP_GenerateSerial(serial, number);
	fprintf(stderr, "EEPROM: Generated serial %s\n", serial);

	err = FTDIEEP_MakeStringDescriptor(data, EEP_MANUFACTURER, &addr, "OpenVizsla");
	err = FTDIEEP_MakeStringDescriptor(data, EEP_PRODUCT, &addr, "ov3p1");
	err = FTDIEEP_MakeStringDescriptor(data, EEP_SERIAL, &addr, serial);

	/* Calculate checksum */

	for (addr = 0; addr < EEP_CHECKSUM; addr++) {
		check = check ^ data[addr];
		check = (check<<1) | (check>>15);
	}
	data[EEP_CHECKSUM] = check;

	/* Write */

	for (addr = 0; addr < EEP_SIZE; addr++) {
		err = FTDIEEP_WriteWord(dev, addr, data[addr]);
		if (err)
			return err;
	}

	/* Verify */

	for (addr = 0; addr < EEP_SIZE; addr++) {
		uint16_t data_read;
		err = FTDIEEP_ReadWord(dev, addr, &data_read);
		if (err)
			return err;
		if (data_read != data[addr])
			return -1;
	}

	fprintf(stderr, "EEPROM: Progammed\n");

	return 0;
}

int FTDIEEP_Erase(FTDIDevice *dev)
{
	int err = 0;
	uint8_t addr;

	err = FTDIEEP_SanityCheck(dev, 1);
	if (err < 0)
		return err;

	for (addr = 0; addr < EEP_SIZE; addr++) {
		err = FTDIEEP_WriteWord(dev, addr, 0xFFFF);
		if (err)
			return err;
	}
	fprintf(stderr, "EEPROM: Erased\n");
	return 0;
}

int FTDIEEP_SanityCheck(FTDIDevice *dev, bool verbose)
{
	int err;
	uint8_t addr;
	uint16_t data[EEP_SIZE];
	uint16_t check = 0xaaaa;

	for (addr = 0; addr < EEP_CHECKSUM; addr++) {
		err = FTDIEEP_ReadWord(dev, addr, &data[addr]);
		if (err)
			return err;
		check = check ^ data[addr];
		check = (check<<1) | (check>>15);
		if (verbose) {
			if ((addr & 15) == 0)
				printf("%02x:", addr);
			printf(" %04x", data[addr]);
			if ((addr & 15) == 15)
				printf("\n");
		}
	}

	err = FTDIEEP_ReadWord(dev, EEP_CHECKSUM, &data[EEP_CHECKSUM]);
	if (verbose)
		printf("(%04x)\n", data[EEP_CHECKSUM]);
	if (err)
		return err;
	if (data[EEP_CHECKSUM] != check) {
		fprintf(stderr, "EEPROM: Device blank or checksum incorrect\n");
		return 1;
	}
	if (data[EEP_MODES] != EEP_MODES_SET(
	                        /* PORT A */ EEP_245FIFO | EEP_D2XX,
	                        /* PORT B */ EEP_245FIFO | EEP_D2XX )) {
		fprintf(stderr, "EEPROM: Incorrect FIFO port modes\n");
		return 2;
	}
	return 0;
}

int FTDIEEP_CheckAndProgram(FTDIDevice *dev, unsigned int number)
{
	int err;
	err = FTDIEEP_SanityCheck(dev, 1);
	if (err < 0)
		return err;
	if (err > 0) {
		err = FTDIEEP_WriteDefaults(dev, number);
		if (err)
			return err;
		fprintf(stderr, "EEPROM: Note: Ignore \"No such device\" errors\n");
		err = FTDIEEP_SanityCheck(dev, 1);
		if (err)
			return err;
		err = FTDIDevice_Reset(dev);
		if (err)
			return err;
	} else {
		fprintf(stderr, "EEPROM: Already programmed\n");
	}

	return 0;
}
