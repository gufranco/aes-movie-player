#include "hw.h"

#include <stddef.h>
#include <string.h>

#include "fmv.h"

fmv_test_machine fmv_test_hw;

void fmv_test_reset(void)
{
    memset(&fmv_test_hw, 0, sizeof(fmv_test_hw));
}

void fmv_test_set_bank_window(const uint8_t *window)
{
    fmv_test_hw.bank_window = window;
}

void fmv_test_set_pad(uint8_t pad, uint8_t status_b)
{
    fmv_test_hw.pad = pad;
    fmv_test_hw.status_b = status_b;
}

uint16_t fmv_test_lspc_mode(void) { return fmv_test_hw.lspc_mode; }

uint16_t fmv_test_prom_bank(void) { return fmv_test_hw.prom_bank; }

uint8_t fmv_test_fix_source(void) { return fmv_test_hw.fix_source; }

uint8_t fmv_test_palette_bank(void) { return fmv_test_hw.palette_bank; }

uint16_t fmv_test_watchdog_kicks(void) { return fmv_test_hw.watchdog_kicks; }

uint16_t fmv_test_vblank_waits(void) { return fmv_test_hw.vblank_waits; }

uint8_t fmv_test_last_sound_command(void) { return fmv_test_hw.last_sound_command; }

uint16_t fmv_test_vram(uint16_t address) { return fmv_test_hw.vram[address]; }

uint16_t fmv_test_palram(uint16_t word) { return fmv_test_hw.palram[word]; }

size_t fmv_test_sizeof_options(void) { return sizeof(fmv_options); }

size_t fmv_test_sizeof_movie(void) { return sizeof(fmv_movie); }

size_t fmv_test_offsetof_options_skip(void) { return offsetof(fmv_options, skip); }

uint32_t fmv_test_player_frame(const fmv_player *player) { return player->frame; }

uint16_t fmv_test_player_stream_bank(const fmv_player *player) { return player->stream_bank; }

uint16_t fmv_test_player_updates(const fmv_player *player) { return player->updates; }

uint16_t fmv_test_player_epoch(const fmv_player *player) { return player->resident_epoch; }

uint16_t fmv_test_player_sprite_offset(const fmv_player *player) { return player->sprite_offset; }

uint8_t fmv_test_player_open(const fmv_player *player) { return player->open; }

size_t fmv_test_sizeof_player(void) { return sizeof(fmv_player); }
