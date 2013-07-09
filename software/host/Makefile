UNAME := $(shell uname)

ifeq ($(UNAME), Darwin)
        # Default install location for libusb-1.0 on Mac OS
	CFLAGS += -I/usr/local/include/libusb-1.0
	LDFLAGS += -L/usr/local/lib -lusb-1.0

	# Large file support
	CFLAGS += -DFILE_OFFSET_BITS=64
else
        # Load libusb via pkg-config
	PACKAGES := libusb-1.0
	CFLAGS += $(shell pkg-config --cflags $(PACKAGES))
	LDFLAGS += $(shell pkg-config --libs $(PACKAGES))

	# Large file support
	CFLAGS += $(shell getconf LFS_CFLAGS)
endif

# Local headers
CFLAGS += -I../include

BIN := memhost
OBJS := main.o fastftdi.o fpgaconfig.o bit_file.o \
        hw_common.o hw_trace.o hw_patch.o iohook_svc.o

CFLAGS += -O3 -g

all: $(BIN)

$(BIN): $(OBJS)
	cc -o $(BIN) $(OBJS) $(LDFLAGS)

*.o: *.h Makefile

clean:
	rm -f $(BIN) $(OBJS)
