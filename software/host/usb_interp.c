#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fastftdi.h"
#include "usb_interp.h"

#ifdef _MSC_VER
#define snprintf _snprintf
#endif

enum {
  HF0_ERR =  0x01, //  Physical layer error
  HF0_OVF =  0x02, // RX Path Overflow
  HF0_CLIP = 0x04, // Clipped by Filter
  HF0_TRUNC = 0x08, // Clipped due to packet length (> 800 bytes)
  HF0_FIRST = 0x10, // First packet of capture session; IE, when the cap hardware was enabled
  HF0_LAST = 0x20, // Last packet of capture session; IE, when the cap hardware was disabled
};


unsigned char packet_buf[2048];
unsigned int packet_buf_len=0;
static const char *names[16] = {
    "WUT", "OUT", "ACK", "DATA0", 
    "PING", "frame", "NYET", "DATA2",
    "SPLIT", "IN", "NAK", "DATA1",
    "PRE-ERR", "SETUP", "STALL", "MDATA"
};

static char ascii(char s) {
  if(s < 0x20) return '.';
  if(s > 0x7E) return '.';
  return s;
}

void hexdump(const void *d, int len) {
  unsigned char *data;
  int i, off;
  data = (unsigned char *)d;
  for (off=0; off<len; off += 16) {
    printf("%08x  ",off);
    for(i=0; i<16; i++)
      if((i+off)>=len) printf("   ");
      else printf("%02x ",data[off+i]);

    printf(" ");
    for(i=0; i<16; i++)
      if((i+off)>=len) printf(" ");
      else printf("%c",ascii(data[off+i]));
  }
}

void hd(unsigned char *outbuf, unsigned int outbuflen, unsigned char *bytes, unsigned int numbytes) {
  unsigned char *ptr = outbuf;

  if ((numbytes * 3) > outbuflen) {
    strncpy(outbuf, "<overflow>", outbuflen - 1);
    outbuf[outbuflen-1] = '\0';
    return;
  }

  while (numbytes > 0) {
    sprintf(outbuf, " %02hhx", *bytes);
    bytes++;
    numbytes--;
    outbuf += 3;
  }
}

enum {
  CRC_BAD = 1,
  CRC_GOOD = 2,
  CRC_NONE = 3,
};

int frameno;
int subframe;
unsigned char highspeed = 1;
unsigned char suppress = 0;
long long ts_delta_pkt;
unsigned long long last_ts_pkt, ts_base = 0;
unsigned int ts_roll_cyc = 1 << 24;
unsigned int last_frameno;
unsigned int last_subframe;
unsigned long long last_ts_frame;
unsigned long long last_ts_print;

void ChandlePacket(unsigned long long ts, unsigned int flags, unsigned char *buf, unsigned int len) {
  unsigned char msg[2048] = "";
  unsigned char flag_field[] = "[        ]";
  unsigned char header[128], frame_print[16]="", subf_print[16]="";
  unsigned int delta_subframe, delta_print;
  float RATE = 60.0e6;

  unsigned char pid;
  //  printf("ChandlePacket(%u, %u, %p, %u)\n", ts, flags, buf, len);

  ts_delta_pkt = ts - last_ts_pkt;
  last_ts_pkt = ts;
  
  if (ts_delta_pkt < 0) {
    ts_base += ts_roll_cyc;
  }
  ts += ts_base;

  if (flags & 0x20) flag_field[3] = 'L';
  if (flags & 0x10) flag_field[4] = 'F';
  if (flags & 0x08) flag_field[5] = 'T';
  if (flags & 0x04) flag_field[6] = 'C';
  if (flags & 0x02) flag_field[7] = 'O';
  if (flags & 0x01) flag_field[8] = 'E';

  if (len == 0) {
    //    printf("Error: zero-len buf?\n");
    //    return;
    goto done;
  }

  pid = buf[0] & 0xF;
  if (((buf[0] >> 4) ^ 0xF) != pid) {
    snprintf(msg, sizeof msg, "Err - bad PID of %02hhx", pid);
    goto done;
  }

  suppress = 0;

  switch(pid) {
  case 0x5: {
    unsigned char frame;
    if (len < 3) {
      strcpy(msg, "RUNT frame");
      break;
    }

    frame = buf[1] | (buf[2] << 8) & 0x7;
    if (frameno == -1) {
      subframe = -1;
    } else {
      if (subframe == -1) {
	if (frame == (frameno + 1) & 0xFF) {
	  subframe = highspeed ? 0 : -1;
	}
      } else {
	subframe++;
	if (subframe == 8) {
	  if (frame == (frameno + 1) & 0xFF) {
	    subframe = 0;
	  } else {
	    snprintf(msg, sizeof msg, "WTF Subframe %d", frameno);
	    subframe = -1;
	  }
	} else if (frameno != frame) {
	  snprintf(msg, sizeof msg, "WTF frameno %d", frameno);
	  subframe = -1;
	}
      }
    }
    
    frameno = frame;
    last_ts_frame = ts;
    suppress = 1;
    snprintf(msg + strlen(msg), sizeof(msg)-strlen(msg),
	     "Frame %d.", frame);
    if (subframe == -1) 
      strcat(msg, "?");
    else
      snprintf(msg + strlen(msg), sizeof(msg)-strlen(msg),
	       "%d", subframe);
    break;
  }
  case 0x3: // DATA0
  case 0xB: // DATA1
  case 0x7: // DATA2
    sprintf(msg, "%s:", names[pid]); // fixme pid->DATA mapping
    hd(msg + strlen(msg), sizeof msg - strlen(msg), buf + 1, len - 1);
    // fixme CRC check
    break;
    
  case 0xF: // MDATA
    strcpy(msg, "MDATA: ");
    hd(msg + strlen(msg), sizeof msg - strlen(msg), buf + 1, len - 1);
    break;
    
  case 0x1: // OUT
  case 0x9: // IN
  case 0xD: // SETUP
  case 0x4: // PING
    // fixme pid->name mapping
    if (len < 3) {
      snprintf(msg, sizeof msg, "RUNT: %s ", names[pid]);
      hd(msg + strlen(msg), sizeof msg - strlen(msg), buf + 1, len - 1);
    } else {
      unsigned char addr = buf[1] & 0x7F;
      unsigned char endp = (buf[2] & 0x7) << 1 | buf[1] >> 7;
      
      snprintf(msg, sizeof msg, "%-5s: %d.%d", names[pid], addr, endp);
    }
    break;
  case 0x2: // ACK
    strcpy(msg, "ACK");
    break;
  case 0xA: // NAK
    strcpy(msg, "NAK");
    break;
  case 0xE: // STALL
    strcpy(msg, "STALL");
    break;
  case 0x6: // NYET
    strcpy(msg, "NYET");
    break;
  case 0xC: // PRE-ERR
    strcpy(msg, "PRE-ERR");
    break;
  case 0x8: // SPLIT
    strcpy(msg, "SPLIT");
    break;
  default:
    strcpy(msg, "WUT");
    break;
  }
  
 done:
  if (suppress) return;
  
  delta_subframe = ts - last_ts_frame;
  delta_print = ts - last_ts_print;
  last_ts_print = ts;
  
  if (frameno != -1 && frameno != 0)
    sprintf(frame_print, "%3d", frameno);
  if (subframe != -1)
    sprintf(subf_print, ".%d", subframe);
  
  snprintf(header, sizeof header, 
	   "%s %10.6f d=%10.6f [%3s%2s +%7.3f] [%3d]",
	   flag_field, ts/RATE, delta_print/RATE,
	   frame_print, subf_print, delta_subframe/RATE * 1E6, len);
  
  printf("%s %s**\n", header, msg);
  //  hexdump(buf, len);
}

unsigned char got_start = 0;

int CStreamCallback (uint8_t *buffer, int length,
			FTDIProgressInfo *progress, void *userdata) {
  unsigned char *p;
  FTDIStreamCallback *cb;
  if (!buffer ||  !length) 
    return 0;
  //    printf("CStreamCallback(%p, %d, %p, %p)\n", buffer, length, progress, userdata);
  //  hexdump(buffer, length);
  cb = (FTDIStreamCallback *)userdata;

  //  printf("packet_buf=%p, packet_buf_len=%d\n", packet_buf, packet_buf_len);
  memcpy(packet_buf + packet_buf_len, buffer, length);
  packet_buf_len += length;
  p = packet_buf;
  if (packet_buf_len > sizeof packet_buf) {
    printf("ERROR: buffer overflow\n");
    exit(0);
  }
  
  //  printf("now, packet_buf=%p, packet_buf_len=%d\n", packet_buf, packet_buf_len);
  while(packet_buf_len > 0) {
    switch(p[0]) {
    case 0x55:
      if (packet_buf_len < 5) {
	printf("IO packet error -- too short (%d < 5)\n", packet_buf_len);
	packet_buf_len--;
	p++;
	break;
      }
      cb(p, 5, progress, NULL);
      packet_buf_len -= 5;
      p+=5;
      break;
    case 0xAA:
      if (packet_buf_len < 2) {
	printf("LFSR packet error -- too short (%d < 2)\n", packet_buf_len);
	packet_buf_len--;
	p++;
	break;
      }
      cb(p, p[1]+2, progress, NULL);
      break;
    case 0xA0: 
      if (packet_buf_len < 8) {
	//	printf("packet cut off, returning\n");
	goto done;
      }
      {
	unsigned int flags = p[1] | (p[2] << 8);
	unsigned int pktsize = p[3] | (p[4] << 8) + 8;
	unsigned int ts = p[5] | (p[6] << 8) | (p[7] << 16);
	if (flags !=0) {
	  printf("PERR: %04X\n", flags);
	}
	//	printf("Packet flags=%04x size=%04x ts=%06x\n", flags, pktsize, ts);
	if (packet_buf_len < pktsize) {
	  //	  printf("packet cut off2, returning\n");
	  goto done;
	}
	if (flags & HF0_FIRST)
	  got_start = 1;
	if (got_start) {
	  ChandlePacket(ts, flags, p+8, pktsize-8);
	}
	if (flags & HF0_LAST)
	  got_start = 0;
	p += pktsize;
	packet_buf_len -= pktsize;
      }
      break;
    default:
      printf("Unknown packet byte %02x, discarding\n", p[0]);
      p++;
      packet_buf_len--;
      break;
    }
  }
 done:
  //  printf("p offset = %d, len = %d\n", p - packet_buf, packet_buf_len);
  memmove(packet_buf, p, packet_buf_len);
  return 0;
}
