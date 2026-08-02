# Next Session Handoff

Quick start for resuming the AES movie player in a fresh session.

## Open the session in the right folder

From a terminal:

```bash
cd ~/aes-movie-player && claude
```

Starting Claude Code from inside `~/aes-movie-player` sets the working directory so all paths resolve against this project, not DoomNG.

## The prompt to send first

Copy this as the first message:

> Continue the AES movie player project. Read the design doc and references under specs/2026-08-02-aes-movie-player/ first. State: the design docs and cited research are committed, no code exists yet. The design is a tile-dictionary vector-quantizer FMV codec for the Neo Geo AES. An offline Python baker produces a C-ROM tile dictionary, a keyframe-and-delta command stream, a mono ADPCM-B soundtrack, and a seek index. The cart runs a small vblank-driven player with a fix-layer transport menu: play, pause, 2x, 5x, 10x, rewind, seek. Targets: 320x224, vblank-locked about 59.185 fps, mono. Hard ceilings: 128 MiB C-ROM per bank from the 20-bit tile number, 16 MiB ADPCM-B. The first step is the spike: bake a 15 to 20 second 320x224 clip into a minimal player, open it in geolith, measure the real tile-dictionary size, and judge the quantization in motion. Reuse from ~/DoomNG: tools/doomng_build/bake/crom.py for the tile packer, palette.py and sprite_palette.py for color and palette clustering, toolchain/build-in-docker.sh for the ngdevkit build and .neo packaging, vendor/ngrayex/hw.h for the SCB reference. Follow the DoomNG rules that apply: reuse before adapt before invent, cite vendor-derived math, persist decisions in the versioned markdown, verify visuals with captures. Start by building the spike against the clip I will point you at, and ask me for the source clip.

## State at handoff

- Design docs and research committed. No code yet. The first step is the spike.
- The spike needs one input from the user: a 15 to 20 second source clip to bake.
- Reuse tooling lives in the separate ~/DoomNG repo. This project is independent.
- Unrelated: the DoomNG full-width sprite work is stashed in ~/DoomNG, not part of this project.

## Key constraints to keep in view

- The only hard video ceiling is 128 MiB of C-ROM per bank window, from the 20-bit tile number. Bankswitch across the 8 banks for longer runtimes.
- Audio is never the limit. ADPCM-B is 16 MiB, one continuous loopable mono sample, about 25 minutes at 22 kHz.
- There is no framebuffer, so no additive residuals. Quality on complex motion is Sega CD and 3DO FMV grade. Static, panning, symmetric, and fade content looks far better.
