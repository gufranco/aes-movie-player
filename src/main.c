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

#define SOUND_CMD_SHIFT_PAGE 0x10
#define SOUND_CMD_PLAY        0x50
#define SOUND_CMD_STOP        0x60
#define SOUND_ACK_TIMEOUT     0x4000

static uint16_t stream_bank = 0xFFFF;
static uint16_t frame_updates;
static uint8_t audio_running = 0;

static void sound_send(uint8_t code)
{
    uint8_t before = REG_SOUND;
    uint16_t guard = SOUND_ACK_TIMEOUT;

    REG_SOUND = code;
    while (REG_SOUND == before && guard--) {
    }
}

static uint16_t audio_page_for(uint32_t frame)
{
    uint64_t scaled = (uint64_t)frame * MOVIE_AUDIO_PAGE_NUM + (MOVIE_AUDIO_PAGE_DEN / 2u);

    return (uint16_t)(scaled / MOVIE_AUDIO_PAGE_DEN);
}

static void audio_seek(uint32_t frame)
{
    uint16_t page = audio_page_for(frame);

    sound_send((uint8_t)(SOUND_CMD_SHIFT_PAGE | ((page >> 12) & 0x0F)));
    sound_send((uint8_t)(SOUND_CMD_SHIFT_PAGE | ((page >> 8) & 0x0F)));
    sound_send((uint8_t)(SOUND_CMD_SHIFT_PAGE | ((page >> 4) & 0x0F)));
    sound_send((uint8_t)(SOUND_CMD_SHIFT_PAGE | (page & 0x0F)));
    sound_send(SOUND_CMD_PLAY);
    audio_running = 1;
}

static void audio_halt(void)
{
    if (audio_running) {
        sound_send(SOUND_CMD_STOP);
        audio_running = 0;
    }
}

static void clear_vram(void)
{
    vram_fill(VRAM_SCB1, VRAM_LOWER_WORDS, 0);
    vram_fill(VRAM_SCB2, VRAM_UPPER_WORDS, 0);
}

/* Colours are refitted per scene, so CRAM holds two epochs at once: the
 * one on screen and the one coming next. They occupy alternating halves
 * of the video allocation, which is what lets the next set be written
 * while the current one is still being read. A whole set is far too much
 * to write in one vblank, so the upload is paid a slice at a time across
 * the epoch that precedes it. */
/* One epoch's own palette count, which is the whole allocation when the
 * movie has a single epoch and half of it when epochs alternate. It is
 * emitted rather than derived so the two cases cannot drift apart. */
#define EPOCH_WORDS      (MOVIE_EPOCH_PALETTES * 16u)
#define EPOCH_SLICE      MOVIE_EPOCH_SLICE

static uint16_t resident_epoch;
static uint16_t loading_epoch;
static uint16_t loading_word;

static volatile uint16_t *epoch_cram(uint16_t epoch)
{
    return PALRAM + (MOVIE_PALETTE_BASE * 16u) + (epoch & 1u) * EPOCH_WORDS;
}

static const uint16_t *epoch_source(uint16_t epoch)
{
    return (const uint16_t *)movie_palettes + (uint32_t)epoch * EPOCH_WORDS;
}

static uint32_t epoch_start(uint16_t epoch)
{
    return ((const uint32_t *)movie_epochs)[epoch];
}

static void clear_reserved_palettes(void)
{
    volatile uint16_t *target = PALRAM;
    uint16_t reserved = MOVIE_PALETTE_BASE * 16;

    while (reserved--) {
        *target++ = 0;
    }
}

static void upload_epoch(uint16_t epoch)
{
    const uint16_t *source = epoch_source(epoch);
    volatile uint16_t *target = epoch_cram(epoch);
    uint16_t words = EPOCH_WORDS;

    while (words--) {
        *target++ = *source++;
    }
}

/* One slice of the epoch after the one on screen. Splitting it this way
 * keeps every frame's share small enough to disappear inside vblank. */
static void upload_palette_slice(void)
{
    const uint16_t *source;
    volatile uint16_t *target;
    uint16_t words = EPOCH_SLICE;

    if (loading_epoch >= MOVIE_EPOCH_COUNT || loading_word >= EPOCH_WORDS) {
        return;
    }
    source = epoch_source(loading_epoch) + loading_word;
    target = epoch_cram(loading_epoch) + loading_word;
    if (loading_word + words > EPOCH_WORDS) {
        words = (uint16_t)(EPOCH_WORDS - loading_word);
    }
    loading_word = (uint16_t)(loading_word + words);
    while (words--) {
        *target++ = *source++;
    }
}

static void begin_loading(uint16_t epoch)
{
    loading_epoch = epoch;
    loading_word = 0;
}

/* Make the colours for a frame resident at once, for boot and for seeks
 * where there is no preceding epoch to spread the cost over. */
static void palettes_for_frame(uint32_t frame)
{
    uint16_t epoch = 0;

    while (epoch + 1u < MOVIE_EPOCH_COUNT && epoch_start((uint16_t)(epoch + 1u)) <= frame) {
        epoch++;
    }
    upload_epoch(epoch);
    resident_epoch = epoch;
    begin_loading((uint16_t)(epoch + 1u));
}

static void follow_epoch(uint32_t frame)
{
    uint16_t next = (uint16_t)(resident_epoch + 1u);

    if (next < MOVIE_EPOCH_COUNT && frame >= epoch_start(next)) {
        resident_epoch = next;
        begin_loading((uint16_t)(next + 1u));
    }
    upload_palette_slice();
}

static void upload_palettes(void)
{
    clear_reserved_palettes();
    palettes_for_frame(0);
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
    frame_updates = 0;

    while (runs--) {
        uint16_t address = *cursor++;
        uint16_t tiles = *cursor++;

        REG_VRAMADDR = address;
        REG_VRAMMOD = 1;
        frame_updates = (uint16_t)(frame_updates + tiles);
        while (tiles--) {
            REG_VRAMRW = *cursor++;
            REG_VRAMRW = *cursor++;
        }
    }
}

/* Cues are fixed width and sorted, so finding the one covering a frame is
 * an index calculation rather than a walk. Records carry a start frame, an
 * end frame, and the glyph rows already laid out and centred by the baker,
 * because none of that fits in a vblank. */
#define SUBTITLE_RECORD_BYTES (8u + MOVIE_SUBTITLE_COLUMNS * MOVIE_SUBTITLE_LINES)

static uint32_t subtitle_word(uint16_t index, uint16_t offset)
{
    const unsigned char *record = movie_subtitles + (uint32_t)index * SUBTITLE_RECORD_BYTES;

    return ((uint32_t)record[offset] << 24) | ((uint32_t)record[offset + 1] << 16) |
           ((uint32_t)record[offset + 2] << 8) | (uint32_t)record[offset + 3];
}

/* Returns MOVIE_SUBTITLE_COUNT when no cue covers the frame, which the
 * caller reads as "show nothing" without needing a second sentinel. */
static uint16_t subtitle_at(uint32_t frame)
{
    uint16_t low = 0;
    uint16_t high = MOVIE_SUBTITLE_COUNT;

    while (low < high) {
        uint16_t mid = (uint16_t)((low + high) >> 1);

        if (subtitle_word(mid, 0) > frame) {
            high = mid;
        } else {
            low = (uint16_t)(mid + 1);
        }
    }
    if (low == 0) {
        return MOVIE_SUBTITLE_COUNT;
    }
    low--;
    if (frame >= subtitle_word(low, 4)) {
        return MOVIE_SUBTITLE_COUNT;
    }
    return low;
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
    palettes_for_frame(landing);
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
    /* Seed these from the pad as it actually reads, so the very first
     * iteration compares against reality. Starting them at zero makes
     * every bit that happens to be set at boot look freshly pressed. */
    uint8_t previous_pad = (uint8_t)~REG_P1CNT;
    uint8_t previous_start = (uint8_t)(~REG_STATUS_B & STATUS_START);
    debug_stats diag = {0};
    uint8_t debug_visible = 0;
    uint8_t subtitles_on = MOVIE_SUBTITLE_COUNT > 0;
    uint16_t resident_cue = MOVIE_SUBTITLE_COUNT;
    uint16_t overlay_tick = 0;
    uint8_t overlay_visible = 0;

    REG_LSPCMODE = LSPC_DISABLE_AUTOANIM;
    watchdog_kick();
    select_cart_fix_rom();
    select_palette_bank_zero();
    clear_vram();
    watchdog_kick();
    upload_palettes();
    watchdog_kick();
    menu_init();
    setup_sprite_grid();

    wait_vblank();
    watchdog_kick();
    apply_frame(0);
    frame = 1;
    audio_seek(0);

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
            if (state == TRANSPORT_PAUSE) {
                audio_halt();
            } else {
                audio_seek(frame);
            }
        }
        if ((pressed & PAD_DOWN) && MOVIE_SUBTITLE_COUNT > 0) {
            subtitles_on = (uint8_t)!subtitles_on;
            if (!subtitles_on) {
                menu_subtitle_hide();
            }
            resident_cue = MOVIE_SUBTITLE_COUNT;
        }
        if (pressed & PAD_UP) {
            debug_visible = (uint8_t)!debug_visible;
            if (!debug_visible) {
                menu_debug_hide();
            }
        }
        if (pressed & PAD_B) {
            state = TRANSPORT_PLAY;
            speed = 1;
            audio_seek(frame);
        }
        if (pressed & PAD_RIGHT) {
            if (state != TRANSPORT_FORWARD) {
                speed_index = 0;
            } else if (speed_index + 1 < SPEED_STEPS) {
                speed_index++;
            }
            state = TRANSPORT_FORWARD;
            speed = speed_ladder[speed_index];
            audio_halt();
        }
        if (pressed & PAD_LEFT) {
            state = TRANSPORT_REWIND;
            speed = 1;
            rewind_countdown = REWIND_FRAMES_PER_STEP;
            audio_halt();
        }
        if (pressed & PAD_C) {
            uint32_t back = seconds_to_frames(SEEK_SECONDS);

            frame = seek_to((frame > back) ? frame - back : 0);
            state = TRANSPORT_PLAY;
            speed = 1;
            audio_seek(frame);
        }
        if (pressed & PAD_D) {
            frame = seek_to(frame + seconds_to_frames(SEEK_SECONDS));
            state = TRANSPORT_PLAY;
            speed = 1;
            audio_seek(frame);
        }

        wait_vblank();
        watchdog_kick();
        follow_epoch(frame);

        switch (state) {
        case TRANSPORT_PAUSE:
            break;
        case TRANSPORT_REWIND:
            if (--rewind_countdown == 0) {
                rewind_countdown = REWIND_FRAMES_PER_STEP;
                if (frame == 0) {
                    state = TRANSPORT_PLAY;
                    audio_seek(frame);
                } else {
                    frame = keyframe_at_or_before(frame - 1);
                    palettes_for_frame(frame);
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
                    palettes_for_frame(0);
                    if (state == TRANSPORT_PLAY) {
                        audio_seek(0);
                    }
                    break;
                }
            }
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

        if (frame_updates > diag.peak_updates) {
            diag.peak_updates = frame_updates;
        }
        if (debug_visible) {
            diag.frame = frame;
            diag.total = MOVIE_FRAME_COUNT;
            diag.epoch = resident_epoch;
            diag.bank = stream_bank;
            diag.audio_page = audio_page_for(frame);
            diag.updates = frame_updates;
            menu_debug_row(&diag, (uint16_t)(overlay_tick & 0x0Fu));
        }
        overlay_tick++;
    }
}
