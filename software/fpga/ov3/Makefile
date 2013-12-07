PYTHONPATH := ../migen:../mibuild
export PYTHONPATH
OVCTL := ../../host/ovctl.py
BUILD := build
BITFILE := $(BUILD)/ov3.bit
FWPKG := $(BUILD)/ov3.fwpkg

PYTHON := python3.3

PY_FILES := $(shell find ovhw ovplatform -name '*.py')

all: $(BITFILE) $(FWPKG)

$(FWPKG): $(BITFILE)
	$(PYTHON) -m zipfile -c $@ $< $(BUILD)/map.txt

$(BITFILE): $(PY_FILES)
	$(PYTHON) build.py build_dir $(BUILD) build_name ov3

clean:
	rm -rf $(BUILD)/*

# Full test of tests anywhere in source tree, including basic sanity 
# tests on per-module basis
testall:
	nosetests --all-modules -v

# Just the explicit testsuite
test:
	nosetests sim -v

run: $(OVCTL) $(BITFILE)
	$(OVCTL) -C -b $(BITFILE) none
