UNAME := $(shell uname)

LIBNAME := libov

ifeq ($(UNAME), Darwin)
        # Default install location for libusb-1.0 on Mac OS
	CFLAGS += -I/usr/local/include/libusb-1.0
	LDFLAGS += -L/usr/local/lib -lusb-1.0

	# Large file support
	CFLAGS += -DFILE_OFFSET_BITS=64

	SO := $(LIBNAME).dylib

else
        # Load libusb via pkg-config
	PACKAGES := libusb-1.0
	CFLAGS += $(shell pkg-config --cflags $(PACKAGES))
	LDFLAGS += $(shell pkg-config --libs $(PACKAGES))

	# Large file support
	CFLAGS += $(shell getconf LFS_CFLAGS)

	CFLAGS += -fPIC

	SO := $(LIBNAME).so
	SO_LDFLAGS := $(LDFLAGS) -shared
endif

# Local headers
CFLAGS += -I../include

BIN := ovctl
OBJS := main.o fastftdi.o fpgaconfig.o bit_file.o \
        hw_common.o ftdieep.o

SO_OBJS := fastftdi.o fpgaconfig.o bit_file.o hw_common.o ftdieep.o

CFLAGS += -O3 -g --std=c99

all: $(BIN) $(SO)

$(BIN): $(OBJS)
	cc -o $(BIN) $(OBJS) $(LDFLAGS)

$(SO): $(SO_OBJS)
	cc -o $@ $^ $(SO_LDFLAGS)

*.o: *.h Makefile

clean:
	rm -f $(BIN) $(SO) $(OBJS)
