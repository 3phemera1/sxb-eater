# Makefile for SXB EhBASIC + Wozmon
#
# Requirements:
#   ca65/ld65  (cc65 suite) - brew install cc65
#   python3
#   minipro    - for flashing
#
# Usage:
#   make              - build ROM image
#   make flash        - build and flash to SST39SF010A
#   make clean        - remove build artifacts

CC65_INC = /usr/local/share/cc65/asminc
BUILD     = build
SXB_ORIG  = SXB_orig.bin

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

WDCMON    = docs/wdc_reference/W65C02SXB.s28

# Patch and build final ROM image
$(BUILD)/SXB_eater.bin: $(BUILD)/eater.bin $(BUILD)/eater.lbl $(SXB_ORIG)
	@if [ -f "$(WDCMON)" ]; then \
		python3 tools/build_rom.py \
			$(BUILD)/eater.bin $(BUILD)/eater.lbl \
			$(SXB_ORIG) $(BUILD)/SXB_eater.bin \
			--wdcmon $(WDCMON); \
	else \
		python3 tools/build_rom.py \
			$(BUILD)/eater.bin $(BUILD)/eater.lbl \
			$(SXB_ORIG) $(BUILD)/SXB_eater.bin; \
	fi

flash: $(BUILD)/SXB_eater.bin
	minipro -p "SST39SF010A" -w $(BUILD)/SXB_eater.bin

clean:
	rm -rf $(BUILD)
