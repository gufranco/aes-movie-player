# References: AES Movie Player research, 2026-08-02

Cited findings from the internet research pass. Confidence noted per cluster.

## Hardware ceilings

- C-ROM sprite graphics use a 20-bit tile number, so 1,048,576 tiles, 128 MiB, are addressable without bankswitching. Beyond that, sprite graphics must be bankswitched, and the console supports 8 banks, which "Giga Power" games used for more. Confidence 9. [Sprites, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=Sprites), [Neo Geo Architecture, Copetti](https://www.copetti.org/writings/consoles/neogeo/), [On Neo-Geo memory bank switching, Neo-Geo Forums](https://neo-geo.com/forums/archive/index.php/t-146574.html)
- A sprite tile is 16x16 pixels, 4bpp planar, 128 bytes, 15 colors plus transparency at index 0. Confidence 9. [Sprite graphics format, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=Sprite_graphics_format), [Sprites, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=Sprites)

## SCB1 sprite control block

- SCB1 is 64 words per sprite, one word pair per tile top to bottom. The even word is the tile number low 16 bits, the odd word holds the high tile-number bits, the palette, and the flip and auto-animation attributes. Total tile number is 20 bits. Confidence 9. [Sprites, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=Sprites)
- Horizontal flip and vertical flip are per-tile attribute bits, so a tile and its mirror share one C-ROM entry. Confidence 8. [Sprites, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=Sprites)
- Auto-animation cycles a tile through 2, 4, or 8 sequential tiles automatically, the 8-frame bit taking priority over the 4-frame bit, with 8 selectable timings. Confidence 8. [Auto animation, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=Auto_animation), [Sprites, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=Sprites)

## Audio, YM2610 ADPCM-B delta-T

- ADPCM-B plays 1.85 kHz to 55.5 kHz set by a 16-bit Delta-N register, f = 55555 x DeltaN / 65535, 4-bit compressed to 16-bit output. Confidence 9. [ADPCM, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=ADPCM), [YM2610 Application Manual, ajworld](https://www.ajworld.net/neogeodev/ym2610am2.html)
- ADPCM-B holds up to 16 MiB, can stream and loop one continuous sample without page-crossing limits, unlike ADPCM-A which is 6 channels, 1 MiB, fixed ~18.5 kHz. This makes ADPCM-B the fit for a minutes-long soundtrack. Confidence 9. [ADPCM, NeoGeo Development Wiki](https://wiki.neogeodev.org/index.php?title=ADPCM), [Anybody know why the Neo Geo uses 2 kinds of ADPCM, nesdev](https://forums.nesdev.org/viewtopic.php?t=24994)

## Prior art

- The Neo Geo Bad Apple demo by HPMAN runs 320x224, 13,167 frames, about 4 minutes, in roughly 3 MB, built with DATLib, DATImage, and NeoSoundBuilder. It is 1-bit black and white with a single palette, so tile dedup is best-case, but it proves tile-streaming FMV with synced audio on real hardware and MiSTer and NeoSD. Confidence 8. [Bad Apple demo, yAronet](https://www.yaronet.com/topics/188010-bad-apple-demo-datlibdatimageneosoundbuilder), [Bad Apple NEO, Internet Archive](https://archive.org/details/badapple_202304)

## Codec model to adapt

- RoQ, used by The 11th Hour and Quake III, is a motion-compensating vector quantizer with per-frame codebooks capped at 256 entries each, so a bounded number of new fragments enter per frame. Decoding is trivial copying, encoding is slow and searches for the least-degrading codebook. This maps directly to an offline baker that builds a C-ROM tile dictionary and caps new tiles per frame. Confidence 8. [RoQ, MultimediaWiki](https://wiki.multimedia.cx/index.php/RoQ), [ROQ file format, idTech4 ModWiki](https://modwiki.dhewm3.org/ROQ_(file_format))

## Color quantization prior art

- Per-tile palette quantization to a small set of 16-color palettes is a solved problem, with tools like the tiled palette quantizer, NeoSpriteConv, NGFX, and DATImage. Optimal solvers can hit near-zero error with only a few 16-color palettes on suitable images. Confidence 7. [Tiled palette quantization tool, NESDev](https://forums.nesdev.org/viewtopic.php?t=24117), [NeoSpriteConv, GitHub](https://github.com/freem/NeoSpriteConv)

## Hardware encodings read from the target decoder, 2026-08-02

The design-time caveats about SCB bit positions and the color word are closed by reading geolith, the emulator this project verifies against. Source: [geolith-libretro](https://github.com/libretro/geolith-libretro), `src/geo_lspc.c`, shallow clone at the commit current on 2026-08-02. Confidence 10 for the emulator's behavior, 9 for real hardware, since geolith models the board rather than guessing.

- SCB1 decode is at `geo_lspc_sprcalc`. The tile number is `even_word | ((odd_word & 0x00F0) << 12)`, hflip is odd bit 0, vflip is odd bit 1, auto-animation is odd bits 3 to 2, and the palette offset is `((odd_word >> 4) & 0x0FF0)`, so the palette is odd bits 15 to 8. This contradicts the one fetched wiki summary that placed the palette at bits 15 to 12 and the flips at bits 8 and 7 to 0.
- Sprite geometry is in the same function. SCB3 bit 6 is the sticky bit, bits 15 to 7 are `512 - top` in line-buffer coordinates, and bits 5 to 0 are the height in tiles. Sticky advances X by `hshrink + 1` and inherits Y, height, and vshrink from the chain head. The sprite loop runs `for i = 1; i < 382`, so sprite 0 is never drawn.
- Tile bytes are decoded at `geo_lspc_tpix`. A tile is 128 bytes of byte-interleaved c1 and c2, columns 8 to 15 in the first 64 bytes and columns 0 to 7 in the last 64, four bytes per pixel row, with bit `n` of a byte holding the pixel at column `n`. The DoomNG `pack_bitmap_to_tiles` layout is byte-exact for this, including its note that the leftmost pixel is the least significant bit.
- The color word is `|D0|R1|G1|B1|R5R4R3R2|G5G4G3G2|B5B4B3B2|`, decoded at `geo_lspc_palconv`. Each channel is five independent bits plus `D0`, a sixth bit shared across all three. This is 15-bit color, not the 12-bit that a 4-bit-per-channel reading would give.
- Two digital-to-analog models exist. `geo_lspc_palgen_raw` scales the six-bit level linearly. `geo_lspc_palgen_resnet` models the board's resistor ladder, 3900, 2200, 1000, 470, and 220 ohms per channel, smooths the curve, and renormalizes, which reaches true black where the raw model bottoms out at 4. The resistor model is the hardware-accurate one and is the local emulator's configured setting, so the baker targets it.
- The C-ROM tile number is masked by `geo_calc_mask(32, csz >> 7)` and the byte offset is taken modulo the C-ROM size, so a non-power-of-two C-ROM aliases high tile numbers onto low ones. The baker pads to a power of two.
- The `.neo` container carries separate V1 and V2 regions, parsed at `geo_neo.c`. V1 is ADPCM-A and V2 is ADPCM-B, which answers the region-naming question for geolith. The MAME dataarea naming still needs its own check before the audio bake.
- The libretro front end crops by the `geolith_overscan_*` options, defaulting to 8 pixels per side, so a capture shows 304 of the 320 active columns unless the options are zeroed.

## Cross-check against MAME, 2026-08-03

geolith models the board; MAME is a second implementation sharing no code with it. Sparse checkout of [mamedev/mame](https://github.com/mamedev/mame), `src/mame/snk` and `src/devices/bus/neogeo`. Confidence 9 for real hardware where both agree.

- Sprite attribute decode at `neogeo_spr.cpp`, `draw_sprites`: `code = ((attr << 12) & 0xf0000) | videoram[offs]`, palette `attr >> 8`, `BIT(attr, 0)` horizontal flip, `BIT(attr, 1)` vertical flip, `BIT(attr, 3)` then `BIT(attr, 2)` for auto-animation. Every field matches geolith exactly, which settles the SCB1 layout the design flagged as uncertain.
- The MAME software-list dataarea for the ADPCM-B voice ROM is `ymsnd:adpcmb`, from `src/devices/bus/neogeo/slot.cpp`. This closes the region-naming question the audio bake was blocked on.
- The watchdog resets the system after about 0.13 seconds, documented in `neogeo.cpp`. That is roughly 7.7 frames, which bounds how long an initialization loop may run without a kick.
- **The two emulators disagree on the program-ROM bank register.** MAME's `write_banksel` masks the value with `0x07`, giving 8 banks of 1 MiB mapped from offset 1 MiB, matching the three-bit latch on the board. geolith derives its mask from the ROM size and permits up to 8 bits. A stream needing more than 8 banks therefore works in geolith and reads the wrong bank on hardware, so the baker enforces the MAME and hardware limit.
- **Neither emulator implements C-ROM bankswitching**, on any board type, including every bootleg mapper MAME carries. The sprite tile number is 20 bits and MAME masks the resulting address with `m_sprite_gfx_address_mask` derived from the region size. The design's claim that 8 C-ROM banks extend video beyond 128 MiB is not supported, and cannot be: 2^20 tiles at 128 bytes is exactly the 128 MiB the 20-bit number addresses.

## Caveats

- The exact split of the 20-bit tile number across the odd attribute word, and the exact palette-field width, were reported inconsistently by one fetched summary. Closed on 2026-08-02 by reading geolith, see the section above. Worth a second confirmation against furrtek's programming manual before the design depends on real-hardware behavior that an emulator could have wrong.
- No source gave a single authoritative maximum for total bankswitched C-ROM. The 8-bank support is corroborated but the practical ceiling on a given flash cart is unverified.
- MAME and neosdconv region naming for the ADPCM-B, delta-t, ROM was not confirmed by the fetched pages and must be checked against a working ADPCM-B homebrew before the audio bake is wired.
