# AES Movie Player: Active Plan (Single Source of Truth)

An offline baker that turns a video file into a Neo Geo AES cartridge ROM, plus a small on-cart player with full transport controls. All heavy processing happens offline in Python bakers. The console decodes nothing at runtime: it streams pre-baked hardware-sprite tile-number updates to the LSPC, plays a pre-encoded ADPCM-B soundtrack, and drives a menu. This file is the SSOT. Research findings with citations live beside it in `references.md`.

## Vision

Play a real movie on a stock Neo Geo AES, full screen, full color, with mono audio and a proper transport UI: play, pause, fast-forward at 2x, 5x, and 10x, rewind, and seek forward and back. Quality is the priority; cart size is not a constraint per the DoomNG standing rule that the cart grows freely. The only hard ceilings are the ones the hardware imposes on addressing, catalogued below.

## Locked targets

| Target | Value | Reason |
|--------|-------|--------|
| Resolution | 320x224, the 240p native raster | Native LSPC active area, no scaling |
| Framerate | Locked to vblank, about 59.185 fps | One movie frame per refresh, even cadence, trivial sync |
| Audio | Mono, ADPCM-B streamed | Single continuous multi-minute sample, hardware-native |
| Transport | play, pause, 2x, 5x, 10x, rewind, seek | Requires random access, so a keyframe-plus-delta codec |

## Hard hardware ceilings

These come from the research pass and bound the design. See `references.md` for citations.

| Resource | Ceiling | Consequence |
|----------|---------|-------------|
| C-ROM tile number | 20 bits, 1,048,576 tiles, 128 MiB per bank window | The video tile dictionary caps at 128 MiB unless C-ROM is bankswitched |
| C-ROM banks | 8 banks supported, used by Giga Power carts | Bankswitching at segment boundaries extends total video beyond 128 MiB |
| Sprite tile | 16x16, 4bpp, 128 bytes, 15 colors plus transparent index 0 | The dictionary unit is a 16x16 tile at 128 bytes |
| ADPCM-B ROM | 16 MiB, one continuous loopable sample | About 25 minutes of audio at 22 kHz, never the limiting factor |
| ADPCM-B rate | 1.85 to 55.5 kHz via Delta-N | Pick around 22 to 32 kHz mono for a good soundtrack |
| Per-scanline sprites | 96 | A 20-column full-screen grid uses 20, far under the limit |
| Total sprites | 381 | 20 for the video grid leaves room for foreground layers |

The single dominant constraint on video is the 128 MiB C-ROM window. Worst case, every one of the 280 on-screen tiles is unique every frame, so a frame costs 280 x 128 = 35,840 bytes and 128 MiB holds about 3,745 frames, roughly 63 seconds at full framerate. Every technique below exists to beat that worst case by a large multiple, and C-ROM bankswitching lifts the ceiling for longer runtimes.

## Architecture

Two halves. The baker is where all intelligence lives. The player is deliberately small.

```mermaid
flowchart LR
  V[source video plus audio] --> B[baker, Python]
  B --> C[C-ROM tile dictionary]
  B --> P[command stream, keyframes plus deltas]
  B --> A[ADPCM-B audio ROM]
  B --> I[seek index]
  C --> ROM[.neo cartridge]
  P --> ROM
  A --> ROM
  I --> ROM
  ROM --> PL[cart player, 68000 plus Z80]
  PL --> LSPC[LSPC draws sprites from C-ROM]
  PL --> YM[YM2610 streams ADPCM-B]
```

### The codec: tile-dictionary VQ with keyframes and deltas

Modeled on RoQ, a motion-compensating vector quantizer, adapted so the C-ROM is the codebook and the LSPC is the decoder.

- **Dictionary.** Every unique 16x16 tile the movie needs, deduplicated globally, stored once in C-ROM. A tile recurring anywhere in space or time is free after the first. Referenced by 20-bit tile number.
- **Keyframes, the I-frames.** Every K frames, and on every scene cut, a full frame: all 280 tile slots rewritten. Keyframes are the random-access entry points that make the transport controls possible. K around 30 to 60, so a seek replays at most half a second to a second of deltas.
- **Deltas, the P-frames.** Between keyframes, only the tile slots that changed. Each delta entry is a slot index plus a 20-bit tile number, run-length coded when changes are contiguous.
- **Command stream.** The ordered list of keyframes and deltas, read by the 68000. Because the 68000 reads it and sits near idle, this stream, unlike the tiles, can be entropy or LZ compressed and decoded at runtime.
- **Seek index.** A small table mapping movie time to the byte offset of each keyframe in the command stream, and to the matching ADPCM-B start address, so a seek re-points both video and audio.

### Data-saving techniques, ranked by impact

All stack multiplicatively. The baker applies them as encoder passes.

1. **Global tile dedup with a tolerance knob.** The foundation. Near-identical tiles collapse within a perceptual distance. The main quality-versus-size control.
2. **Temporal deltas.** Only changed slots per frame. Static regions cost nothing.
3. **Sprite-position motion, the biggest hardware win.** A pan or a translating object moves the sprite X and Y instead of re-tiling. Panning shots become nearly free. This is motion compensation done by the position registers.
4. **Palette-only effects.** Fades, cross-fades, flashes, and tinting change CRAM, not tiles. A fade to black is a handful of color writes and zero tile data.
5. **Flip dedup.** Per-tile hflip and vflip mean a tile and its mirror share one entry. Roughly 2x on symmetric content.
6. **Foreground over background layering.** Static background on low sprite slots, small moving elements on high slots. A talking head streams only the mouth region.
7. **Auto-animation.** Looping motion like fire or a spinning logo uses the hardware 2, 4, or 8 frame auto-cycle at zero per-frame cost.
8. **Compressed command stream.** Entropy or LZ on the delta lists, decoded by the 68000.
9. **Denoise and temporal-stability preprocessing.** Denoise the source first, because noise makes every tile change and destroys deltas. Bias quantization toward reusing the previous frame's tile.
10. **Motion-adaptive keyframe spacing.** More keyframes across cuts and motion, fewer during static shots.

### The honest limit

There is no framebuffer, so there are no additive residuals. Every change resolves to pointing a slot at a tile that already exists in the dictionary, possibly flipped, with some palette. When the needed tile is absent, the only fix is to add it, at C-ROM cost. Residual precision equals dictionary richness equals C-ROM. Complex motion will look quantized, in the Sega CD and 3DO FMV grade, full screen and richly colored but visibly tiled on busy motion. That is the accepted quality target.

## Color

- Quantize each frame to a set of 16-color palettes drawn from the 256 CRAM banks, up to 4096 on-screen colors. Per-tile palette assignment picks the best bank per 16x16 tile.
- Reuse the DoomNG `sprite_palette.py` clustering and `palette.py` `rgb_to_neogeo` and OKLab distance. Reference the tiled-palette-quantizer approach for optimal per-tile assignment.
- Dither in a way that survives tile dedup: prefer ordered dithering keyed to tile position so identical content dithers identically and still dedups, rather than error diffusion that makes every tile unique.
- Keep palettes temporally stable so palette-only fades and cross-fades stay cheap.

## Audio

- One continuous ADPCM-B sample, mono, target 22 to 32 kHz, encoded offline from the soundtrack, up to 16 MiB, about 25 minutes at 22 kHz.
- The YM2610 plays it autonomously. The Z80 driver starts, stops, and re-points the ADPCM-B start address on seek. Video advances one frame per vblank, and the seek index keeps audio and video aligned.
- Trick modes: mute audio during fast-forward and rewind, resume and resync on play. ADPCM-B start address is settable to any 256-byte-aligned point, so seek re-points audio cleanly.
- This path is net-new. DoomNG uses a nullsound placeholder and only an ADPCM-A dataarea, so the ADPCM-B encoder and the Z80 streaming driver are the main new components. Confirm the MAME and neosdconv region naming for delta-t against a working ADPCM-B homebrew first.

## Player and menu

The cart runtime is a small state machine on the 68000, plus the Z80 audio driver.

- **Per vblank:** read the current command-stream position, apply the keyframe or delta by writing SCB tile numbers, advance by the transport state.
- **Transport states:** play advances one frame per vblank; pause holds; 2x, 5x, 10x advance by stepping through keyframes and decimated frames so trick play stays smooth without decoding every intermediate; rewind seeks backward keyframe to keyframe and steps forward in short bursts; seek jumps to the nearest keyframe at or before the target and replays deltas to it.
- **Menu UI:** drawn on the fix layer over the video, an overlay with the transport icons and a scrubber. Controller input drives it. This reuses the DoomNG fix-layer HUD pattern in `i_video.c` and `hud_fix.py`.
- **Sync:** the seek index binds every keyframe to an ADPCM-B start address, so any jump re-points audio and video together.

## Reuse from DoomNG

| Component | Source | Use |
|-----------|--------|-----|
| C-ROM tile packer | `tools/doomng_build/bake/crom.py`, `pack_bitmap_to_tiles`, column-major | Pack dictionary tiles, unchanged |
| Palette conversion | `palette.py`, `rgb_to_neogeo`, `oklab_distance_sq` | Color to Neo Geo, perceptual distance |
| Palette clustering | `sprite_palette.py`, `cluster_sprite_palettes`, `histogram_sprite_pixels` | Per-tile 16-color palette assignment |
| Tile allocation | `sprite_atlas_allocator.py` | Assign dictionary tile bases |
| ngdevkit build and .neo packaging | `toolchain/build-in-docker.sh`, neosdconv, MAME dataarea XML | Adapt for a large C-ROM plus ADPCM-B cart |
| SCB hardware reference | `vendor/ngrayex/hw.h` | SCB1 to SCB4 layout, hshrink, vshrink, auto-increment |
| Docker build resilience | `build-in-docker.sh` retry wrapper | Same flaky-toolchain mitigation |

Net-new: the video encoder passes, the delta and keyframe command-stream format, the seek index, the ADPCM-B encoder, the Z80 streaming driver, the on-cart player and menu, and C-ROM bankswitching support in the packaging.

## Milestones

Spike first, then build outward. Each milestone is verifiable in geolith.

- **M0, spike.** Bake a 15 to 20 second 320x224 clip at vblank rate, mono ADPCM-B, keyframes plus deltas, minimal player, no menu. Open in geolith. Measure real dictionary size and command-stream size, and look at the quantization in motion. This answers the two questions only real footage can: actual C-ROM size and how it looks.
- **M1, encoder core.** Global dictionary, tolerance knob, temporal deltas, per-tile palettes, denoise preprocessing. Report size per technique so we see which pay off.
- **M2, audio.** ADPCM-B encoder and Z80 driver, continuous playback, A/V sync via the seek index.
- **M3, transport and menu.** Keyframe seek index, play, pause, 2x, 5x, 10x, rewind, seek, fix-layer menu, controller input, audio re-pointing on seek.
- **M4, hardware wins.** Sprite-position motion compensation, palette-only fades, flip dedup, auto-animation, compressed command stream.
- **M5, scale.** C-ROM bankswitching for long runtimes, motion-adaptive keyframes, quality tuning.

## Risks and open questions

- Exact SCB1 bit positions for the 20-bit tile number split and palette width must be confirmed against furrtek's programming manual before the SCB emitter is written.
- MAME and neosdconv naming for the ADPCM-B delta-t region is unconfirmed and gates the audio bake.
- geolith accuracy for a very large C-ROM and for ADPCM-B streaming is unverified. Cross-check against MAME.
- Rewind smoothness is inherently limited by forward-only deltas. Keyframe-to-keyframe reverse stepping is the accepted approach; true smooth reverse would need reverse-delta streams at roughly double the data.
- The 128 MiB single-window C-ROM ceiling and 8-bank bankswitching need a concrete flash-cart target to confirm the practical total.

## Reuse rule inheritance

This project inherits the DoomNG working rules that apply: reuse before adapt before invent, cite vendor-derived math, verify visual changes with a capture pair and an A/B, persist decisions in these versioned markdown files, and treat cart size as unlimited while guarding the real hardware ceilings above.
