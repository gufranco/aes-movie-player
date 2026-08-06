#include <stdint.h>

#include "fmv.h"
#include "hw.h"
#include "menu.h"
#include "movie_data.h"
#include "timeline.h"

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

#define SOUND_CMD_SHIFT_PAGE 0x10
#define SOUND_CMD_PLAY        0x50
#define SOUND_CMD_STOP        0x60
#define SOUND_ACK_TIMEOUT     0x4000

static fmv_player video;

static void clear_vram(void)
{
    vram_fill(VRAM_SCB1, VRAM_LOWER_WORDS, 0);
    vram_fill(VRAM_SCB2, VRAM_UPPER_WORDS, 0);
}

static void clear_reserved_palettes(void)
{
    volatile uint16_t *target = PALRAM;
    uint16_t reserved = MOVIE_PALETTE_BASE * 16;

    while (reserved--) {
        *target++ = 0;
    }
}

static uint32_t seconds_to_frames(uint32_t seconds)
{
    return timeline_seconds_to_frames(seconds, MOVIE_FPS_NUM, MOVIE_FPS_DEN);
}

#if MOVIE_SUBTITLE_COUNT > 0
#define SUBTITLE_RECORD_BYTES (8u + MOVIE_SUBTITLE_COLUMNS * MOVIE_SUBTITLE_LINES)

static uint16_t subtitle_at(uint32_t frame)
{
    return timeline_subtitle_at(movie_subtitles, MOVIE_SUBTITLE_COUNT, SUBTITLE_RECORD_BYTES,
                                frame);
}
#endif

int main(void)
{
    transport_state state = TRANSPORT_PLAY;
    uint16_t speed_index = 0;
    uint16_t speed = 1;
    uint32_t frame = 0;
    uint16_t overlay_timer = OVERLAY_HOLD_FRAMES;
    uint16_t rewind_countdown = REWIND_FRAMES_PER_STEP;
    /* Seed these from the pad as it actually reads, so the very first
     * iteration compares against reality. Starting them at zero makes
     * every bit that happens to be set at boot look freshly pressed. */
    uint8_t previous_pad = (uint8_t)~REG_P1CNT;
    uint8_t previous_start = (uint8_t)(~REG_STATUS_B & STATUS_START);
    debug_stats diag = {0};
    uint8_t debug_visible = 0;
#if MOVIE_SUBTITLE_COUNT > 0
    uint8_t subtitles_on = 1;
    uint16_t resident_cue = MOVIE_SUBTITLE_COUNT;
#endif
    uint16_t overlay_tick = 0;
    uint8_t overlay_visible = 0;

    fmv_options options = fmv_defaults();

    options.skip_pad = 0;
    options.skip_start = 0;
    clear_vram();
    watchdog_kick();
    clear_reserved_palettes();
    fmv_open(&video, &fmv_movie_data, &options);
    menu_init();
    fmv_start(&video);
    frame = fmv_position(&video);

    for (;;) {
        uint8_t pad = (uint8_t)~REG_P1CNT;
        uint8_t start = (uint8_t)(~REG_STATUS_B & STATUS_START);
        uint8_t pressed = (uint8_t)(pad & ~previous_pad);
        uint8_t start_pressed = (uint8_t)(start & ~previous_start);
        uint16_t steps;
        uint16_t updates;

        previous_pad = pad;
        previous_start = start;

        if (pressed || start_pressed) {
            overlay_timer = OVERLAY_HOLD_FRAMES;
        }

        if ((pressed & PAD_A) || start_pressed) {
            state = (state == TRANSPORT_PAUSE) ? TRANSPORT_PLAY : TRANSPORT_PAUSE;
            speed = 1;
            if (state == TRANSPORT_PAUSE) {
                fmv_pause(&video);
            } else {
                fmv_resume(&video);
            }
        }
#if MOVIE_SUBTITLE_COUNT > 0
        if (pressed & PAD_DOWN) {
            subtitles_on = (uint8_t)!subtitles_on;
            if (!subtitles_on) {
                menu_subtitle_hide();
            }
            resident_cue = MOVIE_SUBTITLE_COUNT;
        }
#endif
        if (pressed & PAD_UP) {
            debug_visible = (uint8_t)!debug_visible;
            if (!debug_visible) {
                menu_debug_hide();
            }
        }
        if (pressed & PAD_B) {
            state = TRANSPORT_PLAY;
            speed = 1;
            fmv_resume(&video);
        }
        if (pressed & PAD_RIGHT) {
            if (state != TRANSPORT_FORWARD) {
                speed_index = 0;
            } else if (speed_index + 1 < SPEED_STEPS) {
                speed_index++;
            }
            state = TRANSPORT_FORWARD;
            speed = speed_ladder[speed_index];
            fmv_pause(&video);
        }
        if (pressed & PAD_LEFT) {
            state = TRANSPORT_REWIND;
            speed = 1;
            rewind_countdown = REWIND_FRAMES_PER_STEP;
            fmv_pause(&video);
        }
        if (pressed & PAD_C) {
            uint32_t back = seconds_to_frames(SEEK_SECONDS);

            fmv_seek(&video, (frame > back) ? frame - back : 0);
            frame = fmv_position(&video);
            state = TRANSPORT_PLAY;
            speed = 1;
        }
        if (pressed & PAD_D) {
            fmv_seek(&video, frame + seconds_to_frames(SEEK_SECONDS));
            frame = fmv_position(&video);
            state = TRANSPORT_PLAY;
            speed = 1;
        }

        wait_vblank();
        watchdog_kick();

        switch (state) {
        case TRANSPORT_PAUSE:
            fmv_hold(&video);
            break;
        case TRANSPORT_REWIND:
            fmv_hold(&video);
            if (--rewind_countdown == 0) {
                rewind_countdown = REWIND_FRAMES_PER_STEP;
                if (frame == 0) {
                    state = TRANSPORT_PLAY;
                    fmv_resume(&video);
                } else {
                    fmv_seek(&video, frame - 1u);
                    frame = fmv_position(&video);
                }
            }
            break;
        case TRANSPORT_FORWARD:
        case TRANSPORT_PLAY:
        default:
            steps = speed;
            while (steps--) {
                fmv_tick(&video);
                if (fmv_ended(&video)) {
                    fmv_seek(&video, 0);
                    if (state != TRANSPORT_PLAY) {
                        fmv_pause(&video);
                    }
                    break;
                }
            }
            frame = fmv_position(&video);
            break;
        }

        /* Read before anything else touches the raster. Out of vblank
         * here means this frame's work ran past the deadline, which is
         * the player falling behind while the sound chip keeps its own
         * clock: exactly how audio ends up ahead of picture. */
        if (!in_vblank()) {
            diag.overran = 1;
            diag.overruns++;
        } else {
            diag.overran = 0;
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

#if MOVIE_SUBTITLE_COUNT > 0
        if (subtitles_on) {
            uint16_t cue = subtitle_at(frame);

            if (cue != resident_cue) {
                resident_cue = cue;
                if (cue < MOVIE_SUBTITLE_COUNT) {
                    menu_subtitle_show(movie_subtitles + (uint32_t)cue * SUBTITLE_RECORD_BYTES + 8u);
                } else {
                    menu_subtitle_hide();
                }
            }
        }
#endif

        updates = fmv_last_updates(&video);
        if (updates > diag.peak_updates) {
            diag.peak_updates = updates;
        }
        if (debug_visible) {
            diag.frame = frame;
            diag.total = MOVIE_FRAME_COUNT;
            diag.epoch = fmv_epoch(&video);
            diag.bank = fmv_stream_bank(&video);
            diag.audio_page = timeline_audio_page(frame, MOVIE_AUDIO_PAGE_NUM,
                                                  MOVIE_AUDIO_PAGE_DEN);
            diag.updates = updates;
            menu_debug_row(&diag, (uint16_t)(overlay_tick & 0x0Fu));
        }
        overlay_tick++;
    }
}
