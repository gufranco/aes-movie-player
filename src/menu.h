#ifndef AES_MOVIE_MENU_H
#define AES_MOVIE_MENU_H

#include <stdint.h>

typedef enum {
    TRANSPORT_PLAY,
    TRANSPORT_PAUSE,
    TRANSPORT_FORWARD,
    TRANSPORT_REWIND
} transport_state;

void menu_init(void);
void menu_draw(transport_state state, uint16_t speed, uint32_t frame, uint32_t total);
void menu_hide(void);

#endif
