# Next Session Handoff

Quick start for resuming the AES movie player in a fresh session.

## Open the session in the right folder

```bash
cd ~/aes-movie-player && claude
```

Starting from inside the project sets the working directory so paths
resolve here rather than against DoomNG.

## State at handoff

A full ten minute movie bakes, builds, and plays with sound and a working
transport. The baker chooses its own quality tier by measuring the source,
and a rate controller guarantees the result fits the cartridge.

- [`README.md`](README.md) is the entry point: what it is, the ceilings, and
  how to bake, build, and verify.
- The design document under `specs/` carries every measurement and, more
  usefully, the corrections that measurements forced.
- Tests, ruff, and mypy are clean.

## What the full-length bake settled

A 9:56 source at the automatically selected `long` tier:

| Quantity | Value |
|---|---|
| Frames | 35,274 |
| Tiles used | 569,787 of a 1,048,576 budget |
| Dictionary full | no |
| Command stream | 3.0 MB across 3 of 8 banks |
| Controller peak threshold | 0.0155, against a 0.004 tier floor |

Calibration predicted 913,858 tiles and the bake used 569,787, so the
estimate ran about 1.6 times high. That is the safe direction, and it is
inherent to sampling: window boundaries look like cuts and earn keyframes a
real bake never spends, and a short sample cannot see the dictionary reuse
that accumulates across a whole feature. The consequence is that `auto`
picks a more conservative tier than strictly necessary, leaving quality
unspent. Narrowing that gap is the most valuable open piece of work.

## Corrections that overturned earlier conclusions

Anything in an older note contradicting these is wrong.

- **C-ROM bankswitching does not exist.** Neither geolith nor MAME implements
  it on any board, including every bootleg mapper, and it could not exist:
  2^20 tiles at 128 bytes is exactly the 128 MiB the tile number addresses.
  128 MiB is an absolute ceiling, not a per-bank window.
- **The command stream is not a second constraint.** It banks across 8 MiB of
  program ROM and used 3 MB for ten minutes, leaving over half spare.
- **Scene-cut detection was the dominant cost.** Counting slots that differ
  at all fired on 22% of frames on real footage. Counting only slots whose
  source moved past a floor drops that to a handful.
- **Frame blending was rejected on sight** after the error metric endorsed
  it. The metric scores a blended frame as closer to the source sequence;
  the eye reads the same average as a smear.
- **Motion masking is a dead end.** Across factors from 20 to 3000 the tile
  count did not move while error rose fourfold. Unlike a codec with
  residuals, a deferred tile here is interned later regardless.
- **`mean_error` is not a quality measure.** It averages the palette error of
  tiles that were written, so it improves when the encoder skips work. Use
  `displayed_error`, which charges every slot of every frame against the true
  source frame. Neither is trustworthy for temporal levers.

## Reproducing

The source clips are CC-BY Blender Foundation and are not committed.

```bash
mkdir -p assets/clip && cd assets/clip
curl -fLO https://download.blender.org/peach/bigbuckbunny_movies/big_buck_bunny_720p_h264.mov.zip
unzip -o big_buck_bunny_720p_h264.mov.zip && cd ../..

uv --project tools run python -m aesmovie.plan \
  --source assets/clip/big_buck_bunny_720p_h264.mov

uv --project tools run python -m aesmovie.bake \
  --source assets/clip/big_buck_bunny_720p_h264.mov \
  --start 0 --duration 596 --quality auto \
  --build-dir build --preview build/preview.mp4

bash toolchain/build-in-docker.sh
bash tools/scripts/capture_rom.sh 900 build/capture.png
bash tools/scripts/verify_mame.sh
```

A bake outside the build tree needs its artifacts copied into `build/`
first. The generated assembly names its blobs by filename and the build
passes `-I` for the baked directory, so nothing needs rewriting by hand.

## Where to pick up

1. **Close the calibration gap.** The estimate runs about 1.6x high, which
   costs a whole tier of quality on a feature. A second calibration pass on
   the selected tier, or a correction learned from the first minutes of the
   real bake, would recover most of it.
2. **Judge `maximum` and `extreme` visually.** Numbers exist for both and no
   one has looked at them, yet `auto` will select them for a long source.
   Given that blending was rejected after the metric endorsed it, numbers
   alone are not sufficient evidence here.
3. **Validate the ladder on live action.** The relative costs between tiers
   were measured on dense animation. The absolute rate is measured per
   source, but the shape of the ladder is not.

## Constraints to keep in view

- 128 MiB of character ROM is the absolute video ceiling. There is no bank
  register and there cannot be one.
- Audio is rarely the limit. ADPCM-B is 16 MiB, one continuous loopable mono
  sample, about 25 minutes at 22 kHz, and the baker lowers the rate for
  anything longer.
- There is no framebuffer, so no additive residuals. Every correction points
  a slot at a tile that already exists.
