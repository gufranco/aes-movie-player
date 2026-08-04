#include "menu.h"

#include "hw.h"
#include "movie_data.h"

/* The fix layer is 32 rows but the raster only shows rows 2 to 29, so the
 * panel is anchored to row 29 rather than to the nominal bottom. Sitting it
 * any higher leaves a band of video below the overlay. */
/* The fix layer is 32 rows but the raster only shows rows 2 to 29, so the
 * panel is anchored to row 29 rather than to the nominal bottom.
 *
 * The panel reaches the edge but its contents do not. A television
 * overscans, losing something like the outermost cell on every side, so
 * text written on the last visible row is text the viewer may never
 * see. The bottom row is left as padding for that reason. */
#define MENU_LAST_ROW   29
#define MENU_ROWS       5
#define MENU_TOP_ROW    (MENU_LAST_ROW - MENU_ROWS + 1)
#define MENU_COLS       40

#define MENU_EDGE_ROW   MENU_TOP_ROW
#define MENU_BAR_ROW    (MENU_TOP_ROW + 1)
#define MENU_TEXT_ROW   (MENU_TOP_ROW + 3)

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

#define DEBUG_TOP_ROW   2
#define DEBUG_ROWS      9
#define DEBUG_LEFT      1

static uint16_t glyph_for(char code)
{
    if (code >= '0' && code <= '9') {
        return (uint16_t)(FIX_TILE_DIGIT0 + (code - '0'));
    }
    if (code >= 'A' && code <= 'Z') {
        return (uint16_t)(FIX_TILE_A + (code - 'A'));
    }
    switch (code) {
    case '%':
        return FIX_TILE_PERCENT;
    case '.':
        return FIX_TILE_DOT;
    case '-':
        return FIX_TILE_DASH;
    case '/':
        return FIX_TILE_SLASH;
    case ':':
        return FIX_TILE_COLON;
    default:
        return FIX_TILE_PANEL;
    }
}

static uint16_t draw_text(uint16_t col, uint16_t row, const char *text)
{
    while (*text != '\0') {
        fix_poke(col++, row, glyph_for(*text++));
    }
    return col;
}

/* Right-aligned so a value that grows a digit does not shift the label
 * beside it, which matters when reading these while the movie runs. */
static uint16_t draw_number(uint16_t col, uint16_t row, uint32_t value, uint16_t digits)
{
    uint16_t index = digits;

    while (index--) {
        fix_poke((uint16_t)(col + index), row, (uint16_t)(FIX_TILE_DIGIT0 + value % 10u));
        value /= 10u;
    }
    return (uint16_t)(col + digits);
}

static void draw_field(uint16_t col, uint16_t row, const char *label, uint32_t value,
                       uint16_t digits)
{
    uint16_t cursor = draw_text(col, row, label);

    draw_number((uint16_t)(cursor + 1), row, value, digits);
}

void menu_debug_hide(void)
{
    for (uint16_t col = 0; col < MENU_COLS; col++) {
        for (uint16_t row = 0; row < DEBUG_ROWS; row++) {
            fix_poke(col, (uint16_t)(DEBUG_TOP_ROW + row), FIX_TILE_BLANK);
        }
    }
}

/* One row per frame. Writing the whole page at once is several hundred
 * cells, which does not fit in vblank: the writes spill into active
 * display and the sprite layer comes back shredded. Spread this way the
 * page costs about as much as a single row of text. */
void menu_debug_row(const debug_stats *stats, uint16_t slot)
{
    uint16_t row = DEBUG_TOP_ROW;

    if (slot >= DEBUG_ROWS) {
        return;
    }
    for (uint16_t col = 0; col < MENU_COLS; col++) {
        fix_poke(col, (uint16_t)(DEBUG_TOP_ROW + slot), FIX_TILE_PANEL);
    }
    row = (uint16_t)(DEBUG_TOP_ROW + slot);
    switch (slot) {
    case 0:
        draw_field(DEBUG_LEFT, row, "WIDTH", MOVIE_IMAGE_WIDTH, 3);
        draw_field(20, row, "HIGH", MOVIE_IMAGE_HEIGHT, 3);
        break;
    case 1:
        draw_field(DEBUG_LEFT, row, "FPS", MOVIE_FPS_NUM / MOVIE_FPS_DEN, 2);
        draw_field(20, row, "HOLD", MOVIE_FRAME_HOLD, 1);
        break;
    case 2:
        draw_text(DEBUG_LEFT, row, "TIER");
        draw_text((uint16_t)(DEBUG_LEFT + 5), row, MOVIE_TIER_NAME);
        draw_field(20, row, "CHROMA", MOVIE_CHROMA_PERCENT, 3);
        break;
    case 3:
        draw_field(DEBUG_LEFT, row, "EPOCHS", MOVIE_EPOCH_COUNT, 4);
        draw_field(20, row, "CROM", MOVIE_CROM_PERCENT, 3);
        break;
    case 4:
        draw_field(DEBUG_LEFT, row, "AUDIO HZ", MOVIE_AUDIO_HZ, 5);
        draw_field(20, row, "TILES", MOVIE_TILE_COUNT / 1000u, 4);
        break;
    case 5:
        draw_field(DEBUG_LEFT, row, "FRAME", stats->frame, 6);
        draw_field(20, row, "OF", stats->total, 6);
        break;
    case 6:
        draw_field(DEBUG_LEFT, row, "EPOCH", stats->epoch, 4);
        draw_field(20, row, "BANK", stats->bank, 1);
        break;
    case 7:
        draw_field(DEBUG_LEFT, row, "UPDATE", stats->updates, 3);
        draw_field(20, row, "PEAK", stats->peak_updates, 3);
        break;
    default:
        draw_field(DEBUG_LEFT, row, "APAGE", stats->audio_page, 5);
        draw_field(20, row, "OVERRUN", stats->overruns, 5);
        break;
    }
}

/* Subtitles sit two rows above the transport panel so the two never fight
 * for the same cells, and far enough inside the raster that a television
 * losing its outermost row still shows the whole line. */
#define SUBTITLE_TOP_ROW  (MENU_TOP_ROW - 3)

void menu_subtitle_show(const unsigned char *rows)
{
    for (uint16_t line = 0; line < MOVIE_SUBTITLE_LINES; line++) {
        const unsigned char *cells = rows + line * MOVIE_SUBTITLE_COLUMNS;

        for (uint16_t col = 0; col < MENU_COLS; col++) {
            fix_poke(col, (uint16_t)(SUBTITLE_TOP_ROW + line), cells[col]);
        }
    }
}

void menu_subtitle_hide(void)
{
    for (uint16_t line = 0; line < MOVIE_SUBTITLE_LINES; line++) {
        for (uint16_t col = 0; col < MENU_COLS; col++) {
            fix_poke(col, (uint16_t)(SUBTITLE_TOP_ROW + line), FIX_TILE_BLANK);
        }
    }
}

