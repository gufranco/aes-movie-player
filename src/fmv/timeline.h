#ifndef TIMELINE_H
#define TIMELINE_H

#include <stdint.h>

uint32_t timeline_clamp_frame(uint32_t target, uint32_t count);

uint32_t timeline_keyframe_at_or_before(const uint32_t *table, uint32_t count, uint32_t frame);

uint16_t timeline_subtitle_at(const unsigned char *table, uint16_t count, uint16_t stride,
                              uint32_t frame);

uint32_t timeline_seconds_to_frames(uint32_t seconds, uint32_t num, uint32_t den);

uint32_t timeline_frame_to_seconds(uint32_t frame, uint32_t num, uint32_t den);

uint16_t timeline_audio_page(uint32_t frame, uint32_t num, uint32_t den);

uint16_t timeline_bar_fill(uint32_t frame, uint32_t total, uint16_t span);

#endif
