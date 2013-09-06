PYTHONPATH := ../migen:../mibuild
export PYTHONPATH
OVCTL := ../../host/ovctl.py
BUILD := build
BITFILE := $(BUILD)/ov3.bit
FWPKG := $(BUILD)/ov3.fwpkg

PYTHON := python3.3

all: $(BITFILE) $(FWPKG)

$(FWPKG): $(BITFILE)
	$(PYTHON) -m zipfile -c $@ $< $(BUILD)/map.txt

$(BITFILE): *.py
	$(PYTHON) top.py --build-dir $(BUILD) --build-name ov3

clean:
	rm -rf $(BUILD)/*

run: $(OVCTL) $(BITFILE)
	$(OVCTL) -C -b $(BITFILE) none

sim_sdram:
	$(PYTHON) sdram.py
