#include "fmv_audio.h"

#include "hw.h"
#include "timeline.h"

#define SOUND_CMD_SHIFT_PAGE 0x10
#define SOUND_CMD_PLAY       0x50
#define SOUND_CMD_STOP       0x60
#define SOUND_ACK_TIMEOUT    0x4000
#define SOUND_PAGE_NIBBLES   4
#define SOUND_NIBBLE_BITS    4
#define SOUND_NIBBLE_MASK    0x0F

static void sound_send(uint8_t code)
{
    uint8_t before = REG_SOUND;
    uint16_t guard = SOUND_ACK_TIMEOUT;

    REG_SOUND = code;
    while (REG_SOUND == before && guard--) {
    }
}

static void send_page(uint16_t page)
{
    uint16_t nibble = SOUND_PAGE_NIBBLES;

    while (nibble--) {
        uint16_t shift = (uint16_t)(nibble * SOUND_NIBBLE_BITS);

        sound_send((uint8_t)(SOUND_CMD_SHIFT_PAGE | ((page >> shift) & SOUND_NIBBLE_MASK)));
    }
}

void fmv_audio_cue(fmv_player *player, uint32_t frame)
{
    const fmv_movie *movie = player->movie;

    if (!player->options.audio) {
        return;
    }
    send_page(timeline_audio_page(frame, movie->audio_page_num, movie->audio_page_den));
    sound_send(SOUND_CMD_PLAY);
    player->audio_running = 1;
}

void fmv_audio_halt(fmv_player *player)
{
    if (!player->audio_running) {
        return;
    }
    sound_send(SOUND_CMD_STOP);
    player->audio_running = 0;
}
