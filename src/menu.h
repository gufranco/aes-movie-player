#ifndef AES_MOVIE_MENU_H
#define AES_MOVIE_MENU_H

#include <stdint.h>

typedef enum {
    TRANSPORT_PLAY,
    TRANSPORT_PAUSE,
    TRANSPORT_FORWARD,
    TRANSPORT_REWIND
} transport_state;

/* What the debug page reports. Everything here is either a fact of the
 * bake or a live measurement the player can take cheaply once a frame. */
typedef struct {
    uint32_t frame;
    uint32_t total;
    uint16_t epoch;
    uint16_t updates;
    uint16_t peak_updates;
    uint16_t bank;
    uint16_t audio_page;
    uint16_t audio_want;
    uint16_t overruns;
    uint8_t overran;
} debug_stats;

void menu_init(void);
void menu_debug_row(const debug_stats *stats, uint16_t slot);
void menu_debug_hide(void);
void menu_draw(transport_state state, uint16_t speed, uint32_t frame, uint32_t total);
void menu_hide(void);

void menu_subtitle_show(const unsigned char *rows);
void menu_subtitle_hide(void);

#endif
