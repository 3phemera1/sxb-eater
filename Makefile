# Makefile for SXB EhBASIC + Wozmon
#
# Requirements:
#   ca65/ld65  (cc65 suite) - brew install cc65
#   python3
#   minipro    - for flashing with chip programmer (optional)
#
# Usage:
#   make              - build ROM image
#   make flash        - build and flash via chip programmer (minipro)
#   make clean        - remove build artifacts
#
# SXB_orig.bin:
#   A dump of the original SST39SF010A chip is required for the full build.
#   Read it with: minipro -p "SST39SF010A" -r SXB_orig.bin
#   If not present, make will build with --no-orig (no LED diamond on boot).

CC65_INC = /usr/local/share/cc65/asminc
BUILD     = build
SXB_ORIG  = SXB_orig.bin
WDCMON    = docs/wdc_reference/W65C02SXB.s28

.PHONY: all flash clean

all: $(BUILD)/SXB_eater.bin

$(BUILD):
	mkdir -p $(BUILD)

# Assemble and link EhBASIC + wozmon + bios
$(BUILD)/eater.bin $(BUILD)/eater.lbl: $(BUILD) \
		basic/msbasic.s \
		bios/bios_sxb.s \
		wozmon/wozmon.s \
		cfg/sxb.cfg
	ca65 -I$(CC65_INC) -Ibios -Iwozmon -Ibasic -D eater basic/msbasic.s -o $(BUILD)/eater.o
	ld65 -C cfg/sxb.cfg $(BUILD)/eater.o -o $(BUILD)/eater.bin -Ln $(BUILD)/eater.lbl

# Patch and build final ROM image
# - If SXB_orig.bin present: full build with WDC init stubs (LED diamond on boot)
# - If not present: --no-orig build (boots directly to wozmon, no LED diamond)
# - If docs/wdc_reference/W65C02SXB.s28 present: WDCMON embedded in bank 0
$(BUILD)/SXB_eater.bin: $(BUILD)/eater.bin $(BUILD)/eater.lbl
	@if [ -f "$(SXB_ORIG)" ]; then \
		if [ -f "$(WDCMON)" ]; then \
			python3 tools/build_rom.py \
				$(BUILD)/eater.bin $(BUILD)/eater.lbl \
				$(SXB_ORIG) $(BUILD)/SXB_eater.bin \
				--wdcmon $(WDCMON); \
		else \
			python3 tools/build_rom.py \
				$(BUILD)/eater.bin $(BUILD)/eater.lbl \
				$(SXB_ORIG) $(BUILD)/SXB_eater.bin; \
		fi \
	else \
		echo "SXB_orig.bin not found - building without WDC init stubs."; \
		echo "Board will boot directly to wozmon (no LED diamond sequence)."; \
		python3 tools/build_rom.py \
			$(BUILD)/eater.bin $(BUILD)/eater.lbl \
			$(BUILD)/SXB_eater.bin \
			--no-orig; \
	fi

flash: $(BUILD)/SXB_eater.bin
	minipro -p "SST39SF010A" -w $(BUILD)/SXB_eater.bin

clean:
	rm -rf $(BUILD)
