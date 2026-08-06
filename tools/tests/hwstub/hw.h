#ifndef AES_MOVIE_HW_H
#define AES_MOVIE_HW_H

#include <stdint.h>

#define FMV_TEST_VRAM_WORDS 0x10000
#define FMV_TEST_PALRAM_WORDS 4096

typedef struct {
    uint16_t vram[FMV_TEST_VRAM_WORDS];
    uint16_t palram[FMV_TEST_PALRAM_WORDS];
    uint16_t vram_address;
    uint16_t vram_modulo;
    uint16_t lspc_mode;
    uint16_t prom_bank;
    uint16_t vblank_waits;
    uint16_t watchdog_kicks;
    uint8_t last_sound_command;
    uint8_t fix_source;
    uint8_t palette_bank;
    uint8_t pad;
    uint8_t status_b;
    const uint8_t *bank_window;
} fmv_test_machine;

extern fmv_test_machine fmv_test_hw;

static inline uint16_t *fmv_test_next_slot(void)
{
    return &fmv_test_hw.vram[fmv_test_hw.vram_address++ & (FMV_TEST_VRAM_WORDS - 1)];
}

#define REG_VRAMADDR (fmv_test_hw.vram_address)
#define REG_VRAMRW   (*fmv_test_next_slot())
#define REG_VRAMMOD  (fmv_test_hw.vram_modulo)
#define REG_LSPCMODE (fmv_test_hw.lspc_mode)

#define REG_P1CNT    (fmv_test_hw.pad)
#define REG_STATUS_B (fmv_test_hw.status_b)

#define PROM_BANK_SELECT (fmv_test_hw.prom_bank)
#define PROM_BANK_WINDOW ((uintptr_t)fmv_test_hw.bank_window)
#define PROM_BANK_BYTES  0x100000u

#define PALRAM       (fmv_test_hw.palram)
#define PALRAM_WORDS FMV_TEST_PALRAM_WORDS

#define VRAM_SCB1 0x0000
#define VRAM_FIX  0x7000
#define VRAM_SCB2 0x8000
#define VRAM_SCB3 0x8200
#define VRAM_SCB4 0x8400

#define SCB1_WORDS_PER_SPRITE 64
#define SPRITE_COUNT          381
#define FIX_COLS              40
#define FIX_ROWS              32

#define SCB2_NO_SHRINK   0x0FFF
#define SCB3_STICKY      0x0040
#define SCB3_Y_ORIGIN    496
#define LSPC_DISABLE_AUTOANIM 0x0008

static inline void vram_poke(uint16_t address, uint16_t value)
{
    fmv_test_hw.vram[address & (FMV_TEST_VRAM_WORDS - 1)] = value;
}

static inline void watchdog_kick(void) { fmv_test_hw.watchdog_kicks++; }

static inline void vram_fill(uint16_t address, uint16_t count, uint16_t value)
{
    while (count--) {
        fmv_test_hw.vram[address++ & (FMV_TEST_VRAM_WORDS - 1)] = value;
    }
}

static inline void select_cart_fix_rom(void) { fmv_test_hw.fix_source = 0; }

static inline void select_board_fix_rom(void) { fmv_test_hw.fix_source = 1; }

static inline void select_palette_bank_zero(void) { fmv_test_hw.palette_bank = 0; }

static inline void select_palette_bank_one(void) { fmv_test_hw.palette_bank = 1; }

static inline uint16_t scb3_word(int top, uint16_t sticky, uint16_t tiles_high)
{
    return (uint16_t)((((SCB3_Y_ORIGIN - top) & 0x1FF) << 7) | sticky | (tiles_high & 0x3F));
}

static inline uint16_t scb4_word(uint16_t left)
{
    return (uint16_t)((left & 0x1FF) << 7);
}

static inline void wait_vblank(void) { fmv_test_hw.vblank_waits++; }

#define REG_SOUND (fmv_test_hw.last_sound_command)

#endif
