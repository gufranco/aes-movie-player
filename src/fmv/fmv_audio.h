#ifndef FMV_AUDIO_H
#define FMV_AUDIO_H

#include <stdint.h>

#include "fmv.h"

#ifdef FMV_NO_AUDIO

#define fmv_audio_cue(player, frame) ((void)(player), (void)(frame))
#define fmv_audio_halt(player)       ((void)(player))

#else

void fmv_audio_cue(fmv_player *player, uint32_t frame);
void fmv_audio_halt(fmv_player *player);

#endif

#endif
