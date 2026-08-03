#include <stdint.h>

#include "hw.h"
#include "movie_data.h"

#define VIDEO_FIRST_SPRITE 1
#define VIDEO_COLUMNS      MOVIE_GRID_COLS
#define VIDEO_TILE_ROWS    MOVIE_GRID_ROWS
#define VIDEO_TOP_LINE     0
#define VIDEO_LEFT_PIXEL   0

#define VRAM_LOWER_WORDS 0x8000
#define VRAM_UPPER_WORDS 0x0600

static void clear_vram(void)
{
    vram_fill(VRAM_SCB1, VRAM_LOWER_WORDS, 0);
    vram_fill(VRAM_SCB2, VRAM_UPPER_WORDS, 0);
}

static void upload_palettes(void)
{
    const uint16_t *source = (const uint16_t *)movie_palettes;
    volatile uint16_t *target = PALRAM;
    uint16_t reserved = MOVIE_PALETTE_BASE * 16;
    uint16_t words = MOVIE_PALETTE_COUNT * 16;

    while (reserved--) {
        *target++ = 0;
    }
    while (words--) {
        *target++ = *source++;
    }
}

static void setup_sprite_grid(void)
{
    for (uint16_t column = 0; column < VIDEO_COLUMNS; column++) {
        uint16_t sprite = (uint16_t)(VIDEO_FIRST_SPRITE + column);

        vram_poke((uint16_t)(VRAM_SCB2 + sprite), SCB2_NO_SHRINK);
        if (column == 0) {
            vram_poke((uint16_t)(VRAM_SCB3 + sprite), scb3_word(VIDEO_TOP_LINE, 0, VIDEO_TILE_ROWS));
            vram_poke((uint16_t)(VRAM_SCB4 + sprite), scb4_word(VIDEO_LEFT_PIXEL));
        } else {
            vram_poke((uint16_t)(VRAM_SCB3 + sprite), scb3_word(VIDEO_TOP_LINE, SCB3_STICKY, 0));
        }
    }
}

static const uint16_t *apply_frame(const uint16_t *cursor)
{
    uint16_t runs = *cursor++;

    while (runs--) {
        uint16_t address = *cursor++;
        uint16_t tiles = *cursor++;

        REG_VRAMADDR = address;
        REG_VRAMMOD = 1;
        while (tiles--) {
            REG_VRAMRW = *cursor++;
            REG_VRAMRW = *cursor++;
        }
    }
    return cursor;
}

int main(void)
{
    const uint16_t *const start = (const uint16_t *)movie_stream;
    const uint16_t *cursor = start;
    uint32_t frame = 0;

    REG_LSPCMODE = LSPC_DISABLE_AUTOANIM;
    select_cart_fix_rom();
    select_palette_bank_zero();
    clear_vram();
    upload_palettes();
    setup_sprite_grid();

    for (;;) {
        wait_vblank();
        watchdog_kick();
        cursor = apply_frame(cursor);
        if (++frame >= MOVIE_FRAME_COUNT) {
            frame = 0;
            cursor = start;
        }
    }
}
