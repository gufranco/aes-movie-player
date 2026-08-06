#ifndef FMV_H
#define FMV_H

#include <stdint.h>

#define FMV_VERSION "1.0.0"
#define FMV_VERSION_MAJOR 1
#define FMV_VERSION_MINOR 0

#define FMV_QUOTE_(text) #text
#define FMV_QUOTE(text)  FMV_QUOTE_(text)
#define FMV_VERSION_STRING FMV_QUOTE(FMV_VERSION_MAJOR) "." FMV_QUOTE(FMV_VERSION_MINOR)

#define FMV_PAD_UP    0x01
#define FMV_PAD_DOWN  0x02
#define FMV_PAD_LEFT  0x04
#define FMV_PAD_RIGHT 0x08
#define FMV_PAD_A     0x10
#define FMV_PAD_B     0x20
#define FMV_PAD_C     0x40
#define FMV_PAD_D     0x80
#define FMV_PAD_ANY   0xFF
#define FMV_START     0x01

typedef enum {
    FMV_FINISHED = 0,
    FMV_SKIPPED = 1
} fmv_result;

typedef struct {
    const uint8_t *index;
    const uint8_t *keyframes;
    const uint8_t *palettes;
    const uint8_t *epochs;
    const uint8_t *subtitles;
    uint32_t stream_base;
    uint32_t frames;
    uint32_t keyframe_count;
    uint32_t fps_num;
    uint32_t fps_den;
    uint32_t audio_page_num;
    uint32_t audio_page_den;
    uint16_t epoch_count;
    uint16_t epoch_palettes;
    uint16_t epoch_slice;
    uint16_t palette_base;
    uint16_t first_sprite;
    uint16_t grid_cols;
    uint16_t grid_rows;
    uint16_t max_updates;
    uint16_t subtitle_count;
    uint16_t subtitle_columns;
    uint16_t subtitle_lines;
} fmv_movie;

typedef int (*fmv_skip_fn)(void *user);

#define FMV_FIX_CART  0
#define FMV_FIX_BOARD 1

typedef struct {
    uint16_t first_sprite;
    uint16_t top_line;
    uint16_t left_pixel;
    uint16_t lspc_mode;
    uint8_t fix_source;
    uint8_t palette_bank;
    uint8_t prom_bank;
    uint8_t skip_pad;
    uint8_t skip_start;
    uint8_t audio;
    fmv_skip_fn skip;
    void *skip_user;
} fmv_options;

typedef struct {
    const fmv_movie *movie;
    fmv_options options;
    uint32_t frame;
    uint16_t resident_epoch;
    uint16_t loading_epoch;
    uint16_t loading_word;
    uint16_t epoch_words;
    uint16_t sprite_offset;
    uint16_t stream_bank;
    uint16_t updates;
    uint8_t audio_running;
    uint8_t open;
} fmv_player;

fmv_options fmv_defaults(void);

fmv_result fmv_play(const fmv_movie *movie, const fmv_options *options);

void fmv_open(fmv_player *player, const fmv_movie *movie, const fmv_options *options);
void fmv_start(fmv_player *player);
void fmv_tick(fmv_player *player);
void fmv_hold(fmv_player *player);
void fmv_pause(fmv_player *player);
void fmv_resume(fmv_player *player);
void fmv_seek(fmv_player *player, uint32_t frame);
void fmv_close(fmv_player *player);

int fmv_ended(const fmv_player *player);
uint32_t fmv_position(const fmv_player *player);
uint16_t fmv_last_updates(const fmv_player *player);

#endif
