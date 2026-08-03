# AES Movie Player

Play a real movie on a stock Neo Geo AES. Full screen at 320x224, colour,
mono soundtrack, and a working transport: play, pause, fast forward at 2x,
5x and 10x, rewind, and seek.

The console decodes nothing at runtime. An offline baker turns a video file
into cartridge ROM images, and the on-cart player streams pre-baked sprite
tile-number updates to the LSPC, plays a pre-encoded ADPCM-B soundtrack, and
drives a fix-layer menu. Every expensive decision is made once, in Python,
before the cartridge exists.

## How it works

The picture is a 20x14 grid of hardware sprite tiles, 280 slots of 16x16
pixels. Every distinct tile the movie needs is interned once into a global
dictionary in character ROM, and each frame is a short list of "slot 137 now
shows tile 90412". A frame that changes nothing costs two bytes.

Keyframes rewrite all 280 slots and act as seek targets, so the transport
can jump anywhere. Between them, a slot is only rewritten when its content
actually changed and the change is large enough to see.

There is no framebuffer, so there are no residuals. Every correction is a
pointer to a tile that already exists, which means picture quality is
dictionary richness is character ROM.

## Hard ceilings

| Resource | Ceiling | Consequence |
|---|---|---|
| Character ROM | 20-bit tile number, 1,048,576 tiles, 128 MiB | Binds first at every quality tier. There is no bank register and there cannot be one, since 2^20 tiles at 128 bytes is exactly the 128 MiB the number addresses |
| Program ROM | 3-bit bank latch, 8 banks of 1 MiB | Carries the command stream, and keeps around half its space spare throughout |
| ADPCM-B voice ROM | 16 MiB | About 25 minutes at 22 kHz. Only constrains anything past that |
| Sprites per scanline | 96 | The 20-column grid uses 20 |

## Quality tiers

Tile cost is a property of the content, not of the running time. Dense
animation can cost several times what a dialogue scene costs, so the baker
measures the source itself rather than guessing from duration.

Ask what a source can become before committing to a bake:

```bash
uv --project tools run python -m aesmovie.plan --source film.mkv
```

It samples the source, measures the real tile rate, and prints every tier
with the runtime it holds for that source, how far each one overruns, which
one it would pick, and exactly how much to trim to reach the next tier up.
Calibration takes under a minute where a bake takes hours, so the decision
comes before the cost.

| Tier | Picture | Effective fps |
|---|---|---|
| archival | every frame, full colour precision | 59.2 |
| high | every frame, slightly cheaper colour | 59.2 |
| standard | every frame, cheaper colour | 59.2 |
| extended | cheaper colour | 19.7 |
| long | mild denoise | 14.8 |
| maximum | visible softening | 11.8 |
| extreme | heavy softening | 9.9 |

The ladder spans roughly seven times the runtime end to end. The levers are
chroma weighting, which spends less precision on colour than on luminance
because vision resolves luminance far more finely, frame holding, denoise,
and the redraw threshold.

Calibration is deliberately pessimistic. Each sample window boundary looks
like a cut and earns a keyframe a real bake would not spend, and a short
sample cannot see the dictionary reuse that accumulates across a whole
feature. On a ten minute source the estimate came in around 1.6 times the
tiles the full bake actually used, so a selected tier has room rather than a
shortfall.

## Baking

```bash
uv --project tools run python -m aesmovie.bake \
    --source film.mkv --start 0 --duration 596 --quality auto \
    --build-dir build --preview build/preview.mp4
```

`--quality auto` calibrates, prints the same report, and bakes at the tier
it selected. Pass a tier name to pin one. Individual flags such as
`--chroma-weight` override the tier, and the tier overrides the defaults.

A tile budget is enforced during the bake. A tier is chosen from a sample,
and a sample cannot know that the third act is busier than the first, so a
controller compares the recent rate of tile creation against the rate the
remaining budget affords and tightens the redraw threshold while spending
runs hot. Without it the dictionary runs out partway through and every
remaining slot freezes, which ruins the end of a film rather than costing a
little quality across all of it.

## Building the cartridge

```bash
bash toolchain/build-in-docker.sh
```

Runs [`build-in-docker.sh`](toolchain/build-in-docker.sh), which builds the
68000 and Z80 sources with ngdevkit and emits a `.neo` for flash carts and
emulators plus a MAME software-list archive. On non-Linux hosts it
re-executes itself inside a container.

## Verifying

```bash
bash tools/scripts/capture_rom.sh 900 build/check.png
bash tools/scripts/verify_mame.sh
```

[`capture_rom.sh`](tools/scripts/capture_rom.sh) drives the geolith core and
grabs a frame. [`verify_mame.sh`](tools/scripts/verify_mame.sh) runs the same
cartridge under MAME and compares the captured frame against the baker's own
preview with [`verify_capture.py`](tools/scripts/verify_capture.py).

Two emulators are used deliberately. geolith and MAME share no code, so
agreement between them is good evidence about the board rather than about
one author's reading of the documentation. Every hardware encoding this
project depends on was read from their source rather than from prose.

## Repository layout

| Path | Contents |
|---|---|
| [`src/`](src) | The 68000 player, the fix-layer menu, and the Z80 sound driver |
| [`tools/aesmovie/`](tools/aesmovie) | The baker: decode, colour, palettes, tile dictionary, encoder, audio, ROM containers |
| [`tools/tests/`](tools/tests) | Test suite, including independent transcriptions of geolith used as oracles |
| [`tools/scripts/`](tools/scripts) | Capture and verification helpers |
| [`toolchain/`](toolchain) | The containerised build |

## Requirements

ffmpeg and ffprobe on the path, `uv` for the Python side, Docker on
non-Linux hosts for the build, and a Neo Geo BIOS for the emulators.

## Credits

Test footage is Big Buck Bunny and Tears of Steel, both by the Blender
Foundation under CC BY.
