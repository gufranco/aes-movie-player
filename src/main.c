#include <stdint.h>

#include "hw.h"
#include "menu.h"
#include "movie_data.h"

#define VIDEO_FIRST_SPRITE 1
#define VIDEO_COLUMNS      MOVIE_GRID_COLS
#define VIDEO_TILE_ROWS    MOVIE_GRID_ROWS
#define VIDEO_TOP_LINE     0
#define VIDEO_LEFT_PIXEL   0

#define VRAM_LOWER_WORDS 0x8000
#define VRAM_UPPER_WORDS 0x0600

#define PAD_UP    0x01
#define PAD_DOWN  0x02
#define PAD_LEFT  0x04
#define PAD_RIGHT 0x08
#define PAD_A     0x10
#define PAD_B     0x20
#define PAD_C     0x40
#define PAD_D     0x80
#define STATUS_START 0x01

#define OVERLAY_HOLD_FRAMES 180
#define OVERLAY_REDRAW_MASK 0x07
#define REWIND_FRAMES_PER_STEP 6
#define SEEK_SECONDS 10u

static const uint16_t speed_ladder[] = {2, 5, 10};
#define SPEED_STEPS ((uint16_t)(sizeof(speed_ladder) / sizeof(speed_ladder[0])))

static uint16_t stream_bank = 0xFFFF;

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

static void apply_frame(uint32_t frame)
{
    const uint32_t *index = (const uint32_t *)movie_index;
    uint32_t offset = index[frame];
    uint16_t wanted = (uint16_t)(offset / PROM_BANK_BYTES);
    const uint16_t *cursor;
    uint16_t runs;

    if (wanted != stream_bank) {
        PROM_BANK_SELECT = wanted;
        stream_bank = wanted;
    }
    cursor = (const uint16_t *)(PROM_BANK_WINDOW + (offset % PROM_BANK_BYTES));
    runs = *cursor++;

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
}

static uint32_t keyframe_at_or_before(uint32_t frame)
{
    const uint32_t *table = (const uint32_t *)movie_keyframes;
    uint32_t low = 0;
    uint32_t high = MOVIE_KEYFRAME_COUNT;

    while (low + 1 < high) {
        uint32_t mid = (low + high) >> 1;

        if (table[mid] <= frame) {
            low = mid;
        } else {
            high = mid;
        }
    }
    return table[low];
}

static uint32_t seconds_to_frames(uint32_t seconds)
{
    return (seconds * MOVIE_FPS_NUM) / MOVIE_FPS_DEN;
}

static uint32_t seek_to(uint32_t target)
{
    uint32_t landing;

    if (target >= MOVIE_FRAME_COUNT) {
        target = MOVIE_FRAME_COUNT - 1;
    }
    landing = keyframe_at_or_before(target);
    apply_frame(landing);
    return landing;
}

int main(void)
{
    transport_state state = TRANSPORT_PLAY;
    uint16_t speed_index = 0;
    uint16_t speed = 1;
    uint32_t frame = 0;
    uint16_t overlay_timer = OVERLAY_HOLD_FRAMES;
    uint16_t rewind_countdown = REWIND_FRAMES_PER_STEP;
    uint8_t previous_pad = 0;
    uint8_t previous_start = 0;
    uint16_t overlay_tick = 0;
    uint8_t overlay_visible = 0;

    REG_LSPCMODE = LSPC_DISABLE_AUTOANIM;
    select_cart_fix_rom();
    select_palette_bank_zero();
    clear_vram();
    upload_palettes();
    menu_init();
    setup_sprite_grid();

    for (;;) {
        uint8_t pad = (uint8_t)~REG_P1CNT;
        uint8_t start = (uint8_t)(~REG_STATUS_B & STATUS_START);
        uint8_t pressed = (uint8_t)(pad & ~previous_pad);
        uint8_t start_pressed = (uint8_t)(start & ~previous_start);
        uint16_t steps;

        previous_pad = pad;
        previous_start = start;

        if (pressed || start_pressed) {
            overlay_timer = OVERLAY_HOLD_FRAMES;
        }

        if ((pressed & PAD_A) || start_pressed) {
            state = (state == TRANSPORT_PAUSE) ? TRANSPORT_PLAY : TRANSPORT_PAUSE;
            speed = 1;
        }
        if (pressed & PAD_B) {
            state = TRANSPORT_PLAY;
            speed = 1;
        }
        if (pressed & PAD_RIGHT) {
            if (state != TRANSPORT_FORWARD) {
                speed_index = 0;
            } else if (speed_index + 1 < SPEED_STEPS) {
                speed_index++;
            }
            state = TRANSPORT_FORWARD;
            speed = speed_ladder[speed_index];
        }
        if (pressed & PAD_LEFT) {
            state = TRANSPORT_REWIND;
            speed = 1;
            rewind_countdown = REWIND_FRAMES_PER_STEP;
        }
        if (pressed & PAD_C) {
            uint32_t back = seconds_to_frames(SEEK_SECONDS);

            frame = seek_to((frame > back) ? frame - back : 0);
            state = TRANSPORT_PLAY;
            speed = 1;
        }
        if (pressed & PAD_D) {
            frame = seek_to(frame + seconds_to_frames(SEEK_SECONDS));
            state = TRANSPORT_PLAY;
            speed = 1;
        }

        wait_vblank();
        watchdog_kick();

        switch (state) {
        case TRANSPORT_PAUSE:
            break;
        case TRANSPORT_REWIND:
            if (--rewind_countdown == 0) {
                rewind_countdown = REWIND_FRAMES_PER_STEP;
                if (frame == 0) {
                    state = TRANSPORT_PLAY;
                } else {
                    frame = keyframe_at_or_before(frame - 1);
                    apply_frame(frame);
                }
            }
            break;
        case TRANSPORT_FORWARD:
        case TRANSPORT_PLAY:
        default:
            steps = speed;
            while (steps--) {
                apply_frame(frame);
                if (++frame >= MOVIE_FRAME_COUNT) {
                    frame = 0;
                    break;
                }
            }
            break;
        }

        if (overlay_timer) {
            overlay_timer--;
            if (!overlay_visible || (overlay_tick & OVERLAY_REDRAW_MASK) == 0) {
                menu_draw(state, speed, frame, MOVIE_FRAME_COUNT);
            }
            overlay_visible = 1;
        } else if (overlay_visible) {
            menu_hide();
            overlay_visible = 0;
        }
        overlay_tick++;
    }
}
