#ifndef AES_MOVIE_HW_H
#define AES_MOVIE_HW_H

#include <stdint.h>

#define REG_VRAMADDR (*(volatile uint16_t *)0x3C0000)
#define REG_VRAMRW   (*(volatile uint16_t *)0x3C0002)
#define REG_VRAMMOD  (*(volatile uint16_t *)0x3C0004)
#define REG_VRAMPAIR (*(volatile uint32_t *)0x3C0000)
#define REG_LSPCMODE (*(volatile uint16_t *)0x3C0006)

#define REG_SOUND    (*(volatile uint8_t *)0x320000)

#define REG_P1CNT    (*(volatile uint8_t *)0x300000)
#define REG_WATCHDOG (*(volatile uint8_t *)0x300001)
#define REG_STATUS_B (*(volatile uint8_t *)0x380000)

#define PROM_BANK_SELECT (*(volatile uint16_t *)0x2FFFF0)
#define PROM_BANK_WINDOW 0x200000u
#define PROM_BANK_BYTES  0x100000u

#define REG_BRDFIX   (*(volatile uint8_t *)0x3A000B)
#define REG_PALBANK1 (*(volatile uint8_t *)0x3A000F)
#define REG_CRTFIX   (*(volatile uint8_t *)0x3A001B)
#define REG_PALBANK0 (*(volatile uint8_t *)0x3A001F)

#define PALRAM       ((volatile uint16_t *)0x400000)
#define PALRAM_WORDS 4096
#define PALRAM_BACKDROP 4095

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

static inline void vram_addr(uint16_t address) { REG_VRAMADDR = address; }
static inline void vram_mod(uint16_t modulo) { REG_VRAMMOD = modulo; }
static inline void vram_write(uint16_t value) { REG_VRAMRW = value; }

/* The address port sits at 0x3C0000 and the data port immediately after
 * it, so one 32-bit write lands both: the high word in the address port
 * and the low word in the data port. That halves the instruction count
 * of a scattered write, which is the shape the overlay draws in and the
 * shape the stream falls back to when a run covers a single slot. The
 * technique is the one libNG uses in its raster command processor. */
static inline void vram_poke(uint16_t address, uint16_t value)
{
    REG_VRAMPAIR = ((uint32_t)address << 16) | value;
}

static inline void watchdog_kick(void) { REG_WATCHDOG = 0; }

#define VRAM_FILL_WATCHDOG_INTERVAL 2048

static inline void vram_fill(uint16_t address, uint16_t count, uint16_t value)
{
    uint16_t until_kick = VRAM_FILL_WATCHDOG_INTERVAL;

    REG_VRAMADDR = address;
    REG_VRAMMOD = 1;
    while (count--) {
        REG_VRAMRW = value;
        if (--until_kick == 0) {
            until_kick = VRAM_FILL_WATCHDOG_INTERVAL;
            watchdog_kick();
        }
    }
}

static inline void select_cart_fix_rom(void) { REG_CRTFIX = 0; }

static inline void select_palette_bank_zero(void) { REG_PALBANK0 = 0; }

static inline uint16_t scb3_word(int top, uint16_t sticky, uint16_t tiles_high)
{
    return (uint16_t)((((SCB3_Y_ORIGIN - top) & 0x1FF) << 7) | sticky | (tiles_high & 0x3F));
}

static inline uint16_t scb4_word(uint16_t left)
{
    return (uint16_t)((left & 0x1FF) << 7);
}

static inline int in_vblank(void) { return (REG_LSPCMODE & 0x8000) == 0; }

static inline void wait_vblank(void)
{
    while (in_vblank()) {
    }
    while (!in_vblank()) {
    }
}

#endif
