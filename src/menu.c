#include "menu.h"

#include "hw.h"
#include "movie_data.h"

#define MENU_TOP_ROW    24
#define MENU_ROWS       4
#define MENU_LEFT_COL   0
#define MENU_COLS       40
#define MENU_TEXT_ROW   25
#define MENU_BAR_ROW    27
#define MENU_GLYPH_COL  2
#define MENU_TIME_COL   4
#define MENU_BAR_COL    2
#define MENU_BAR_CELLS  36

#define SECONDS_PER_MINUTE 60u
#define TIME_DIGITS 11

static uint16_t fix_word(uint16_t tile)
{
    return (uint16_t)((FIX_PALETTE << 12) | (tile & 0x0FFF));
}

static void fix_poke(uint16_t col, uint16_t row, uint16_t tile)
{
    vram_poke((uint16_t)(VRAM_FIX + col * 32 + row), fix_word(tile));
}

static uint32_t frame_to_seconds(uint32_t frame)
{
    return (uint32_t)((frame * (uint32_t)MOVIE_FPS_DEN) / (uint32_t)MOVIE_FPS_NUM);
}

static void draw_clock(uint16_t col, uint32_t seconds)
{
    uint32_t minutes = seconds / SECONDS_PER_MINUTE;
    uint32_t rest = seconds % SECONDS_PER_MINUTE;

    fix_poke(col, MENU_TEXT_ROW, (uint16_t)(FIX_TILE_DIGIT0 + (minutes / 10u) % 10u));
    fix_poke((uint16_t)(col + 1), MENU_TEXT_ROW, (uint16_t)(FIX_TILE_DIGIT0 + minutes % 10u));
    fix_poke((uint16_t)(col + 2), MENU_TEXT_ROW, FIX_TILE_COLON);
    fix_poke((uint16_t)(col + 3), MENU_TEXT_ROW, (uint16_t)(FIX_TILE_DIGIT0 + rest / 10u));
    fix_poke((uint16_t)(col + 4), MENU_TEXT_ROW, (uint16_t)(FIX_TILE_DIGIT0 + rest % 10u));
}

static uint16_t state_glyph(transport_state state)
{
    switch (state) {
    case TRANSPORT_PAUSE:
        return FIX_TILE_PAUSE;
    case TRANSPORT_FORWARD:
        return FIX_TILE_FORWARD;
    case TRANSPORT_REWIND:
        return FIX_TILE_REWIND;
    case TRANSPORT_PLAY:
    default:
        return FIX_TILE_PLAY;
    }
}

void menu_init(void)
{
    const uint16_t *source = (const uint16_t *)movie_fix_palette;
    volatile uint16_t *target = PALRAM + FIX_PALETTE * 16;

    for (uint16_t i = 0; i < 16; i++) {
        target[i] = source[i];
    }
}

void menu_hide(void)
{
    for (uint16_t col = 0; col < MENU_COLS; col++) {
        for (uint16_t row = 0; row < MENU_ROWS; row++) {
            fix_poke(col, (uint16_t)(MENU_TOP_ROW + row), FIX_TILE_BLANK);
        }
    }
}

void menu_draw(transport_state state, uint16_t speed, uint32_t frame, uint32_t total)
{
    uint32_t elapsed = frame_to_seconds(frame);
    uint32_t duration = frame_to_seconds(total);
    uint16_t filled = (uint16_t)((total > 1u) ? (frame * MENU_BAR_CELLS) / (total - 1u) : 0u);
    uint16_t col;
    uint16_t row;

    for (col = 0; col < MENU_COLS; col++) {
        for (row = 0; row < MENU_ROWS; row++) {
            fix_poke(col, (uint16_t)(MENU_TOP_ROW + row), FIX_TILE_PANEL);
        }
    }

    fix_poke(MENU_GLYPH_COL, MENU_TEXT_ROW, state_glyph(state));
    if (speed > 1u) {
        fix_poke((uint16_t)(MENU_GLYPH_COL + 1), MENU_TEXT_ROW,
                 (uint16_t)(FIX_TILE_DIGIT0 + (speed / 10u) % 10u));
        fix_poke((uint16_t)(MENU_GLYPH_COL + 2), MENU_TEXT_ROW,
                 (uint16_t)(FIX_TILE_DIGIT0 + speed % 10u));
    }

    draw_clock(MENU_TIME_COL + 2, elapsed);
    fix_poke(MENU_TIME_COL + 8, MENU_TEXT_ROW, FIX_TILE_SLASH);
    draw_clock(MENU_TIME_COL + 10, duration);

    for (col = 0; col < MENU_BAR_CELLS; col++) {
        fix_poke((uint16_t)(MENU_BAR_COL + col), MENU_BAR_ROW,
                 col <= filled ? FIX_TILE_BAR_FILLED : FIX_TILE_BAR_EMPTY);
    }
}
