#include "timeline.h"

#define SUBTITLE_START_OFFSET 0u
#define SUBTITLE_END_OFFSET   4u

static uint32_t subtitle_word(const unsigned char *table, uint16_t stride, uint16_t index,
                              uint16_t offset)
{
    const unsigned char *record = table + (uint32_t)index * stride;

    return ((uint32_t)record[offset] << 24) | ((uint32_t)record[offset + 1] << 16) |
           ((uint32_t)record[offset + 2] << 8) | (uint32_t)record[offset + 3];
}

uint32_t timeline_clamp_frame(uint32_t target, uint32_t count)
{
    if (count == 0u) {
        return 0u;
    }
    if (target >= count) {
        return count - 1u;
    }
    return target;
}

uint32_t timeline_keyframe_at_or_before(const uint32_t *table, uint32_t count, uint32_t frame)
{
    uint32_t low = 0;
    uint32_t high = count;

    if (count == 0u) {
        return 0u;
    }
    while (low + 1u < high) {
        uint32_t mid = (low + high) >> 1;

        if (table[mid] <= frame) {
            low = mid;
        } else {
            high = mid;
        }
    }
    return table[low];
}

uint16_t timeline_subtitle_at(const unsigned char *table, uint16_t count, uint16_t stride,
                              uint32_t frame)
{
    uint16_t low = 0;
    uint16_t high = count;

    while (low < high) {
        uint16_t mid = (uint16_t)((low + high) >> 1);

        if (subtitle_word(table, stride, mid, SUBTITLE_START_OFFSET) > frame) {
            high = mid;
        } else {
            low = (uint16_t)(mid + 1);
        }
    }
    if (low == 0u) {
        return count;
    }
    low--;
    if (frame >= subtitle_word(table, stride, low, SUBTITLE_END_OFFSET)) {
        return count;
    }
    return low;
}

uint32_t timeline_seconds_to_frames(uint32_t seconds, uint32_t num, uint32_t den)
{
    if (den == 0u) {
        return 0u;
    }
    return (uint32_t)(((uint64_t)seconds * num) / den);
}

uint32_t timeline_frame_to_seconds(uint32_t frame, uint32_t num, uint32_t den)
{
    if (num == 0u) {
        return 0u;
    }
    return (uint32_t)(((uint64_t)frame * den) / num);
}

uint16_t timeline_audio_page(uint32_t frame, uint32_t num, uint32_t den)
{
    uint64_t scaled;

    if (den == 0u) {
        return 0u;
    }
    scaled = (uint64_t)frame * num + (den / 2u);
    return (uint16_t)(scaled / den);
}

uint16_t timeline_bar_fill(uint32_t frame, uint32_t total, uint16_t span)
{
    if (total <= 1u) {
        return 0u;
    }
    if (frame >= total - 1u) {
        return span;
    }
    return (uint16_t)((frame * span) / (total - 1u));
}
