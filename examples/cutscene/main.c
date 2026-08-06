#include <ngdevkit/neogeo.h>
#include <ngdevkit/registers.h>

#include "fmv.h"
#include "movie_data.h"

#define FIX_COLUMNS 40
#define FIX_ROWS    32
#define FIX_FIRST_VISIBLE_ROW 2
#define FIX_LAST_VISIBLE_ROW  29

#define PALETTE_WORDS 16
#define BACKDROP_WORD 4095

#define TITLE_ROW    10
#define SUBTITLE_ROW 12
#define PROMPT_ROW   16
#define OUTCOME_ROW  18

#define RASTER_LINE_SHIFT 7
#define RASTER_LINE_MASK  0x01FF
#define RASTER_FIRST_DRAWN 0x0100
#define RASTER_LAST_DRAWN  0x01EF

#define PAD_ANY_BUTTON (FMV_PAD_A | FMV_PAD_B | FMV_PAD_C | FMV_PAD_D)

static u16 fix_word(u16 tile)
{
    return (u16)((FIX_PALETTE << 12) | (tile & 0x0FFF));
}

static void fix_poke(u16 col, u16 row, u16 tile)
{
    *REG_VRAMADDR = (u16)(ADDR_FIXMAP + col * FIX_ROWS + row);
    *REG_VRAMMOD = 1;
    *REG_VRAMRW = fix_word(tile);
}

static void fix_clear(void)
{
    for (u16 col = 0; col < FIX_COLUMNS; col++) {
        *REG_VRAMADDR = (u16)(ADDR_FIXMAP + col * FIX_ROWS);
        *REG_VRAMMOD = 1;
        for (u16 row = 0; row < FIX_ROWS; row++) {
            *REG_VRAMRW = fix_word(FIX_TILE_BLANK);
        }
    }
}

static u16 glyph_for(char code)
{
    if (code >= '0' && code <= '9') {
        return (u16)(FIX_TILE_DIGIT0 + (code - '0'));
    }
    if (code >= 'A' && code <= 'Z') {
        return (u16)(FIX_TILE_A + (code - 'A'));
    }
    switch (code) {
    case '.':
        return FIX_TILE_DOT;
    case '-':
        return FIX_TILE_DASH;
    case ':':
        return FIX_TILE_COLON;
    default:
        return FIX_TILE_BLANK;
    }
}

static u16 text_length(const char *text)
{
    u16 length = 0;

    while (text[length] != '\0') {
        length++;
    }
    return length;
}

static void draw_centred(u16 row, const char *text)
{
    u16 col = (u16)((FIX_COLUMNS - text_length(text)) / 2);

    while (*text != '\0') {
        fix_poke(col++, row, glyph_for(*text++));
    }
}

static void upload_own_palettes(void)
{
    const u16 *source = (const u16 *)movie_fix_palette;
    volatile u16 *target = MMAP_PALBANK1 + FIX_PALETTE * PALETTE_WORDS;

    for (u16 word = 0; word < PALETTE_WORDS; word++) {
        target[word] = source[word];
    }
    MMAP_PALBANK1[BACKDROP_WORD] = 0x8000;
}

static int in_vblank(void)
{
    u16 line = (u16)((*REG_LSPCMODE >> RASTER_LINE_SHIFT) & RASTER_LINE_MASK);

    return line < RASTER_FIRST_DRAWN || line > RASTER_LAST_DRAWN;
}

static void wait_vblank(void)
{
    while (in_vblank()) {
    }
    while (!in_vblank()) {
    }
}

static void draw_title(fmv_result outcome)
{
    draw_centred(TITLE_ROW, "AES MOVIE PLAYER");
    draw_centred(SUBTITLE_ROW, "CUTSCENE EXAMPLE");
    draw_centred(PROMPT_ROW, "PRESS START TO REPLAY");
    draw_centred(OUTCOME_ROW,
                 outcome == FMV_SKIPPED ? "CUTSCENE SKIPPED" : "CUTSCENE FINISHED");
}

int main(void)
{
    fmv_options options = fmv_defaults();
    fmv_result outcome;
    u8 previous_start;

    options.skip_pad = PAD_ANY_BUTTON;
    options.skip_start = 1;

    upload_own_palettes();
    fix_clear();

    outcome = fmv_play(&fmv_movie_data, &options);

    fix_clear();
    draw_title(outcome);
    previous_start = (u8)(~*REG_STATUS_B & FMV_START);

    for (;;) {
        u8 start = (u8)(~*REG_STATUS_B & FMV_START);
        u8 start_pressed = (u8)(start & ~previous_start);

        previous_start = start;
        wait_vblank();

        if (start_pressed) {
            fix_clear();
            outcome = fmv_play(&fmv_movie_data, &options);
            fix_clear();
            draw_title(outcome);
            previous_start = (u8)(~*REG_STATUS_B & FMV_START);
        }
    }
}
