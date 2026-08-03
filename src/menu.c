#include "menu.h"

#include "hw.h"
#include "movie_data.h"

#define MENU_TOP_ROW    24
#define MENU_ROWS       4
#define MENU_COLS       40

#define MENU_EDGE_ROW   24
#define MENU_BAR_ROW    25
#define MENU_TEXT_ROW   27

#define MENU_MARGIN     2
#define MENU_BAR_COL    MENU_MARGIN
#define MENU_BAR_CELLS  (MENU_COLS - MENU_MARGIN * 2)

#define MENU_ICON_COL   MENU_MARGIN
#define MENU_SPEED_COL  (MENU_ICON_COL + 2)
#define MENU_CLOCK_CELLS 5
#define MENU_TOTAL_COL  (MENU_COLS - MENU_MARGIN - MENU_CLOCK_CELLS)
#define MENU_SLASH_COL  (MENU_TOTAL_COL - 2)
#define MENU_ELAPSED_COL (MENU_SLASH_COL - 1 - MENU_CLOCK_CELLS)

#define SECONDS_PER_MINUTE 60u

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

static void draw_clock(uint16_t col, uint16_t row, uint32_t seconds)
{
    uint32_t minutes = seconds / SECONDS_PER_MINUTE;
    uint32_t rest = seconds % SECONDS_PER_MINUTE;

    fix_poke(col, row, (uint16_t)(FIX_TILE_DIGIT0 + (minutes / 10u) % 10u));
    fix_poke((uint16_t)(col + 1), row, (uint16_t)(FIX_TILE_DIGIT0 + minutes % 10u));
    fix_poke((uint16_t)(col + 2), row, FIX_TILE_COLON);
    fix_poke((uint16_t)(col + 3), row, (uint16_t)(FIX_TILE_DIGIT0 + rest / 10u));
    fix_poke((uint16_t)(col + 4), row, (uint16_t)(FIX_TILE_DIGIT0 + rest % 10u));
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

static void draw_seek_bar(uint32_t frame, uint32_t total)
{
    uint16_t span = MENU_BAR_CELLS - 1u;
    uint16_t filled = (uint16_t)((total > 1u) ? (frame * span) / (total - 1u) : 0u);
    uint16_t col;

    for (col = 0; col < MENU_BAR_CELLS; col++) {
        uint16_t tile;

        if (col < filled) {
            tile = FIX_TILE_BAR_FILLED;
        } else if (col == 0u) {
            tile = FIX_TILE_BAR_CAP_LEFT;
        } else if (col == MENU_BAR_CELLS - 1u) {
            tile = FIX_TILE_BAR_CAP_RIGHT;
        } else {
            tile = FIX_TILE_BAR_EMPTY;
        }
        fix_poke((uint16_t)(MENU_BAR_COL + col), MENU_BAR_ROW, tile);
    }
    fix_poke((uint16_t)(MENU_BAR_COL + filled), MENU_BAR_ROW, FIX_TILE_BAR_KNOB);
}

void menu_draw(transport_state state, uint16_t speed, uint32_t frame, uint32_t total)
{
    uint16_t col;
    uint16_t row;

    for (col = 0; col < MENU_COLS; col++) {
        fix_poke(col, MENU_EDGE_ROW, FIX_TILE_PANEL_TOP);
        for (row = 1; row < MENU_ROWS; row++) {
            fix_poke(col, (uint16_t)(MENU_TOP_ROW + row), FIX_TILE_PANEL);
        }
    }

    draw_seek_bar(frame, total);

    fix_poke(MENU_ICON_COL, MENU_TEXT_ROW, state_glyph(state));
    if (speed > 1u) {
        fix_poke(MENU_SPEED_COL, MENU_TEXT_ROW,
                 (uint16_t)(FIX_TILE_DIGIT0 + (speed / 10u) % 10u));
        fix_poke((uint16_t)(MENU_SPEED_COL + 1), MENU_TEXT_ROW,
                 (uint16_t)(FIX_TILE_DIGIT0 + speed % 10u));
    }

    draw_clock(MENU_ELAPSED_COL, MENU_TEXT_ROW, frame_to_seconds(frame));
    fix_poke(MENU_SLASH_COL, MENU_TEXT_ROW, FIX_TILE_SLASH);
    draw_clock(MENU_TOTAL_COL, MENU_TEXT_ROW, frame_to_seconds(total));
}
