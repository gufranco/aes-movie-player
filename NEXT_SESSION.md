# Next Session Handoff

Quick start for resuming the AES movie player in a fresh session.

## Open the session in the right folder

From a terminal:

```bash
cd ~/aes-movie-player && claude
```

Starting Claude Code from inside `~/aes-movie-player` sets the working directory so all paths resolve against this project, not DoomNG.

## State at handoff

The spike is done. A 20 second clip bakes, builds, boots in geolith, and the rendered picture matches the baker's own model of it.

- The baker is complete for the techniques it implements: 207 tests, 99 percent coverage, ruff and mypy clean.
- The cart plays the clip at the vblank rate and loops. There is no menu, no transport, and no audio yet.
- Capture verification is automated. `tools/scripts/verify_capture.py` finds the baked frame that best matches a geolith screenshot and reports the error, so a regression shows up as a number rather than an opinion.
- The design document under `specs/` carries the measurements, the lever sweep, and the corrections they forced.

## Reproducing the spike

The source clip is CC-BY Blender Foundation and is not committed. Fetch it, then bake and build:

```bash
mkdir -p assets/clip && cd assets/clip
curl -fLO https://download.blender.org/peach/bigbuckbunny_movies/big_buck_bunny_720p_h264.mov.zip
unzip -o big_buck_bunny_720p_h264.mov.zip && cd ../..

uv --project tools run python -m aesmovie.bake \
  --source assets/clip/big_buck_bunny_720p_h264.mov \
  --start 425 --duration 20.0 --build-dir build \
  --scene-cut-ratio 0.90 --tolerance 0.0005 --keyframe-interval 90 \
  --preview build/preview-spike.mkv --report-json build/report-spike.json

bash toolchain/build-in-docker.sh
bash tools/scripts/capture_rom.sh 900 build/capture.png
uv --project tools run python tools/scripts/verify_capture.py \
  --capture build/capture.png --preview build/preview-spike.mkv
```

The `.mkv` preview is lossless and is what the verifier compares against. Pass a `.mp4` instead for a small shareable copy.

## What the spike settled

- C-ROM costs about 30 MB per minute on hard content, so one 128 MiB bank holds 4.5 minutes and the 8 banks hold roughly 36 minutes. A feature does not fit; a 30 minute program does.
- Quality came out better than expected. Mean error is about 0.025 Oklab, near the just-noticeable threshold, and tiling is not obvious in stills.
- Flip dedup is worth nothing on real footage, 0.08 percent, against an estimate of 2x.
- The command stream is a second constraint nobody accounted for. At 1.08 MB per minute it outgrows the 1 MiB P-ROM window long before C-ROM fills.

## The first thing to decide next

Command-stream size gates the transport work more than the controls themselves do. Before building the menu, pick how the stream is stored: bankswitched P-ROM, an LZ or entropy codec decoded by the 68000, or a keyframe cadence tuned per scene. Keyframes are most of the stream, so cheaper keyframes may be the largest single win.

## Key constraints to keep in view

- The only hard video ceiling is 128 MiB of C-ROM per bank window, from the 20-bit tile number. Bankswitch across the 8 banks for longer runtimes.
- Audio is never the limit. ADPCM-B is 16 MiB, one continuous loopable mono sample, about 25 minutes at 22 kHz. The `.neo` V2 region is ADPCM-B; the MAME dataarea name still needs checking.
- There is no framebuffer, so no additive residuals. Every correction points a slot at a tile that already exists.
