# Makefile for SXB EhBASIC + Wozmon + Bank 1 C Monitor
#
# Requirements:
#   ca65/ld65/cc65  (cc65 suite) - brew install cc65
#   python3
#   minipro         - for flashing with chip programmer (optional)
#
# Usage:
#   make                  - build ROM image (includes bank 1 monitor by default)
#   make NO_MONITOR=1     - build ROM image without the bank 1 C monitor
#   make flash            - build and flash via chip programmer (minipro)
#   make clean            - remove build artifacts
#
# SXB_orig.bin:
#   A dump of the original SST39SF010A chip is required for the full build.
#   Read it with: minipro -p "SST39SF010A" -r SXB_orig.bin
#   If not present, make will build with --no-orig (no LED diamond on boot).

# ── Toolchain paths ──────────────────────────────────────────────────────────
# Detect cc65 prefix from PATH so the build works on both Intel (/usr/local)
# and Apple Silicon (/opt/homebrew) Homebrew installations.
CC65_PREFIX := $(shell dirname $$(dirname $$(which cc65 2>/dev/null)) 2>/dev/null)
CC65_INC    := $(CC65_PREFIX)/share/cc65/asminc
CC65_LIB    := $(CC65_PREFIX)/share/cc65/lib

CC65 = cc65
CA65 = ca65
LD65 = ld65

BUILD    = build
SXB_ORIG = SXB_orig.bin
WDCMON   = docs/wdc_reference/W65C02SXB.s28

# ── Bank 1 C monitor sources ─────────────────────────────────────────────────
MONITOR_DIR  = monitor
MONITOR_CSRC = $(MONITOR_DIR)/main.c \
               $(MONITOR_DIR)/srec.c \
               $(MONITOR_DIR)/via.c  \
               $(MONITOR_DIR)/pia.c  \
               $(MONITOR_DIR)/acia.c \
               $(MONITOR_DIR)/util.c
MONITOR_SSRC = $(MONITOR_DIR)/crt0.s \
               $(MONITOR_DIR)/serial.s

MONITOR_COBJ = $(patsubst $(MONITOR_DIR)/%.c, $(BUILD)/monitor/%.o, $(MONITOR_CSRC))
MONITOR_SOBJ = $(patsubst $(MONITOR_DIR)/%.s, $(BUILD)/monitor/%.o, $(MONITOR_SSRC))
MONITOR_OBJS = $(MONITOR_SOBJ) $(MONITOR_COBJ)

# ── Monitor integration toggle ───────────────────────────────────────────────
ifdef NO_MONITOR
MONITOR_DEP  =
MONITOR_FLAG =
else
MONITOR_DEP  = $(BUILD)/monitor.bin
MONITOR_FLAG = --monitor $(BUILD)/monitor.bin
endif

.PHONY: all flash clean hello

all: $(BUILD)/SXB_eater.bin $(BUILD)/hello.bin $(BUILD)/test_beep.bin

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/monitor:
	mkdir -p $(BUILD)/monitor

# ── Bank 3: assemble and link EhBASIC + wozmon + bios ───────────────────────
$(BUILD)/eater.bin $(BUILD)/eater.lbl: $(BUILD) \
		basic/msbasic.s \
		bios/bios_sxb.s \
		wozmon/wozmon.s \
		cfg/sxb.cfg
	$(CA65) -I$(CC65_INC) -Ibios -Iwozmon -Ibasic -D eater basic/msbasic.s -o $(BUILD)/eater.o
	$(LD65) -C cfg/sxb.cfg $(BUILD)/eater.o -o $(BUILD)/eater.bin -Ln $(BUILD)/eater.lbl

# ── Bank 1: C monitor ────────────────────────────────────────────────────────

# Compile C sources to assembly, then assemble to objects
$(BUILD)/monitor/%.s: $(MONITOR_DIR)/%.c | $(BUILD)/monitor
	$(CC65) --cpu 65C02 -t none -O -I$(MONITOR_DIR) -o $@ $<

$(BUILD)/monitor/%.o: $(BUILD)/monitor/%.s
	$(CA65) --cpu 65C02 -o $@ $<

# Assemble hand-written monitor assembly sources
$(BUILD)/monitor/crt0.o: $(MONITOR_DIR)/crt0.s | $(BUILD)/monitor
	$(CA65) --cpu 65C02 -I$(MONITOR_DIR) -o $@ $<

$(BUILD)/monitor/serial.o: $(MONITOR_DIR)/serial.s | $(BUILD)/monitor
	$(CA65) --cpu 65C02 -I$(MONITOR_DIR) -o $@ $<

# Link the monitor binary (32 KB, bank 1)
$(BUILD)/monitor.bin: $(MONITOR_OBJS)
	$(LD65) -C $(MONITOR_DIR)/cfg/monitor.cfg \
		$(BUILD)/monitor/crt0.o \
		$(BUILD)/monitor/serial.o \
		$(BUILD)/monitor/main.o \
		$(BUILD)/monitor/srec.o \
		$(BUILD)/monitor/via.o \
		$(BUILD)/monitor/pia.o \
		$(BUILD)/monitor/acia.o \
		$(BUILD)/monitor/util.o \
		$(CC65_LIB)/none.lib \
		-o $@ -Ln $(BUILD)/monitor.lbl

# ── Hello World example ──────────────────────────────────────────────────────
# Standalone user program that runs in RAM under the bank 1 C monitor.
# Load address: $4000.  Upload with:
#   python3 tools/upload.py <port> build/hello.bin --addr 4000 --run

HELLO_DIR  = hello
TEST_DIR   = monitor

$(BUILD)/hello:
	mkdir -p $(BUILD)/hello

$(BUILD)/test:
	mkdir -p $(BUILD)/test

$(BUILD)/hello/hello.s: $(HELLO_DIR)/hello.c | $(BUILD)/hello
	$(CC65) --cpu 65C02 -t none -O -I$(MONITOR_DIR) -o $@ $<

$(BUILD)/hello/hello.o: $(BUILD)/hello/hello.s
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/hello/crt0.o: $(HELLO_DIR)/crt0.s | $(BUILD)/hello
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/hello/serial.o: $(MONITOR_DIR)/serial.s | $(BUILD)/hello
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/test/test_beep.s: $(TEST_DIR)/test_beep.c | $(BUILD)/test
	$(CC65) --cpu 65C02 -t none -O -I$(MONITOR_DIR) -o $@ $<

$(BUILD)/test/test_beep.o: $(BUILD)/test/test_beep.s
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/test/crt0.o: $(HELLO_DIR)/crt0.s | $(BUILD)/test
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/test/serial.o: $(MONITOR_DIR)/serial.s | $(BUILD)/test
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/test/stdio_eater.s: $(MONITOR_DIR)/stdio_eater.c | $(BUILD)/test
	$(CC65) --cpu 65C02 -t none -O -I$(MONITOR_DIR) -o $@ $<

$(BUILD)/test/stdio_eater.o: $(BUILD)/test/stdio_eater.s
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/test/via.s: $(MONITOR_DIR)/via.c | $(BUILD)/test
	$(CC65) --cpu 65C02 -t none -O -I$(MONITOR_DIR) -o $@ $<

$(BUILD)/test/via.o: $(BUILD)/test/via.s
	$(CA65) --cpu 65C02 -o $@ $<

$(BUILD)/hello.bin: $(BUILD)/hello/crt0.o $(BUILD)/hello/hello.o $(BUILD)/hello/serial.o $(HELLO_DIR)/cfg/hello.cfg
	$(LD65) -C $(HELLO_DIR)/cfg/hello.cfg \
		$(BUILD)/hello/crt0.o \
		$(BUILD)/hello/hello.o \
		$(BUILD)/hello/serial.o \
		$(CC65_LIB)/none.lib \
		-o $@ -Ln $(BUILD)/hello.lbl

$(BUILD)/test_beep.bin: $(BUILD)/test/crt0.o $(BUILD)/test/test_beep.o $(BUILD)/test/serial.o $(BUILD)/test/stdio_eater.o $(BUILD)/test/via.o $(HELLO_DIR)/cfg/hello.cfg
	$(LD65) -C $(HELLO_DIR)/cfg/hello.cfg \
		$(BUILD)/test/crt0.o \
		$(BUILD)/test/test_beep.o \
		$(BUILD)/test/serial.o \
		$(BUILD)/test/stdio_eater.o \
		$(BUILD)/test/via.o \
		$(CC65_LIB)/none.lib \
		-o $@ -Ln $(BUILD)/test_beep.lbl

hello: $(BUILD)/hello.bin

# ── Final ROM image ──────────────────────────────────────────────────────────
# - If SXB_orig.bin present: full build with WDC init stubs (LED diamond on boot)
# - If not present: --no-orig build (boots directly to wozmon, no LED diamond)
# - If docs/wdc_reference/W65C02SXB.s28 present: WDCMON embedded in bank 0
# - Unless NO_MONITOR=1: bank 1 contains the C monitor
$(BUILD)/SXB_eater.bin: $(BUILD)/eater.bin $(BUILD)/eater.lbl $(MONITOR_DEP)
	@if [ -f "$(SXB_ORIG)" ]; then \
		if [ -f "$(WDCMON)" ]; then \
			python3 tools/build_rom.py \
				$(BUILD)/eater.bin $(BUILD)/eater.lbl \
				$(SXB_ORIG) $(BUILD)/SXB_eater.bin \
				--wdcmon $(WDCMON) $(MONITOR_FLAG); \
		else \
			python3 tools/build_rom.py \
				$(BUILD)/eater.bin $(BUILD)/eater.lbl \
				$(SXB_ORIG) $(BUILD)/SXB_eater.bin \
				$(MONITOR_FLAG); \
		fi \
	else \
		echo "SXB_orig.bin not found - building without WDC init stubs."; \
		echo "Board will boot directly to wozmon (no LED diamond sequence)."; \
		python3 tools/build_rom.py \
			$(BUILD)/eater.bin $(BUILD)/eater.lbl \
			$(BUILD)/SXB_eater.bin \
			--no-orig $(MONITOR_FLAG); \
	fi

flash: $(BUILD)/SXB_eater.bin
	minipro -p "SST39SF010A" -w $(BUILD)/SXB_eater.bin

clean:
	rm -rf $(BUILD)
