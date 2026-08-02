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

## Caveats

- The exact split of the 20-bit tile number across the odd attribute word, and the exact palette-field width, were reported inconsistently by one fetched summary. The authoritative facts, 20-bit tile number and 256 palettes and per-tile hflip and vflip and 2/4/8 auto-anim, are corroborated, but the precise bit positions should be confirmed against furrtek's programming manual before writing the SCB emitter.
- No source gave a single authoritative maximum for total bankswitched C-ROM. The 8-bank support is corroborated but the practical ceiling on a given flash cart is unverified.
- MAME and neosdconv region naming for the ADPCM-B, delta-t, ROM was not confirmed by the fetched pages and must be checked against a working ADPCM-B homebrew before the audio bake is wired.
