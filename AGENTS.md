# Engineering contract

The rules for changing this repository. [FAMILY.md](FAMILY.md) is the standard
every member of the family follows, and it binds first; this file adds what is
particular to the Neo Geo. The [README](README.md) says what the project is and
how to use it.

## One family, no ports

Owner's instruction, 2026-10-15: the players and the core are members of one
family of tools. Never describe one as a port, fork, translation or derivative
of another, in a README, a commit, a comment or any other text, in any
language, and never tell which member came first: work moves between the
members in every direction, and more consoles will join.

Owner's instruction, 2026-10-17: the menu is one menu across the family, as
alike in function and look as each console allows, and this player's menu in
`src/player/menu.c` is the model the others copy. Its colours come from
`fmvcore.font.MENU_COLOURS` and its art from the core's glyphs, so a change to
either reaches every player; a change to the menu's layout or behaviour is
made in smsgg-media-player in the same task. The rule is in FAMILY.md.

## Original hardware is the only target

Everything here is built to run on a real AES or MVS board. A clean emulator
run, a green suite and a good-looking capture are evidence about an emulator,
not about the board.

- A change that touches anything the board can disagree with, the VRAM write
  loop, the bank latch, the palette and fix latches, the interrupt or the ROM
  header, is unverified until it has run on a board. Say so in the change and
  ask for the run.
- Where a documented figure and a looser measured one disagree, the documented
  one binds.

### The binding numbers

| Rule | Value | Source |
|---|---|---|
| Cycles between consecutive VRAM data writes | at least 12 | NeoGeo Development Wiki, VRAM page |
| Cycles after a VRAM write before a new address | at least 16 | same |
| Program ROM bank latch | 3 bits, 8 banks of 1 MiB | MAME `neogeo.cpp`, which masks the register with `0x07` |
| Character ROM | 20-bit tile number, 128 MiB, no bankswitching | geolith `src/geo_lspc.c`, MAME `neogeo_spr.cpp` |
| Raster | 384 by 264 at a 6 MHz dot clock, 59.185 Hz, every region | geolith `LSPC_SCANLINES` |
| Watchdog | about 0.13 s | [`docs/hardware.md`](docs/hardware.md) |

Every bit layout the player depends on is in [`docs/hardware.md`](docs/hardware.md),
read out of both emulators' decoders.

## Gates

| Claim | Command |
|:--|:--|
| The baker holds | `uv --project tools run ruff format --check tools/`, `ruff check tools/`, `mypy tools/neogeomedia tools/scripts` |
| The behaviour holds | `NEOGEOMEDIA_CC_REQUIRED=1 NEOGEOMEDIA_FFMPEG_REQUIRED=1 uv --project tools run python -m pytest tools/tests --cov=neogeomedia --cov=tools/scripts --cov-config=tools/pyproject.toml --cov-fail-under=95` |
| A commit is clean | `.githooks/pre-commit`, installed once by `make hooks` |
| The regression set holds | `uv --project tools run python tools/scripts/fetch_clips.py`, then the behaviour gate with `NEOGEOMEDIA_CLIPS_REQUIRED=1` |
| It builds | `make rom` |
| The C holds | `make analyse` |
| No VRAM write pair is under its floor | `make timing`, after `make rom` |
| The sound driver answers its commands | `NEOGEOMEDIA_ROM_REQUIRED=1 uv --project tools run python -m pytest tools/tests/test_sound_on_z80.py`, after `make rom` |
| A cartridge comes out end to end | `uv --project tools run python -m neogeomedia.cartridge <source> --quality q17` |
| It runs on a board | the owner's AES or MVS; nothing on this machine settles it |

Nothing here is verified by compiling. Run the gates and read their output
before claiming a change is done.

## Hard rules

1. **Docker for every build.** The toolchain image pins Ubuntu by digest, its
   packages by a dated snapshot and ngdevkit by version and SHA-256, and runs
   as the calling user.
2. **No comments or docstrings in source.** Reasoning goes in the commit
   message, this file, the development log, [`tools/DESIGN.md`](tools/DESIGN.md)
   for the baker, or [`docs/hardware.md`](docs/hardware.md) for the player.
3. **Functions under 30 lines, files under 500**, `mypy` strict, `ruff` clean,
   coverage 95%.
4. **The tier file is a property of films, not of a run.**
   [`neogeomedia-tiers.json`](neogeomedia-tiers.json) is committed; a bake made
   to test something, such as a demo capture, never lands in it.
5. **An emulator never takes the screen.** A scripted run is headless and makes
   no sound; a run the owner asked to watch opens windowed and minimised, never
   full screen. See "Running an emulator" below.

## The regression set

Six films of different kinds, the same ones the Master System player bakes,
are baked on every test run at rung q17 over a two-second window each. The
manifest, [`tools/clips.manifest.json`](tools/clips.manifest.json), holds
each film's identity, credit, licence, window and two ceilings: the displayed
error and the tiles a second the bake may spend. The ceilings sit 15% above
what the films measured on 2026-11-02 with the dither on by default, so a
change has to make the picture or the dictionary measurably worse to fail,
and ffmpeg differing slightly between this Mac and the runner does not. The
displayed error is per pixel, so the dither raised it 3% to 23% by
construction while the blurred error fell; a ceiling guards against a
regression and never judges a dither. Only the synthetic film is
committed, in the core submodule as `fixtures/synthetic.mp4`; the rest are
fetched and verified by SHA-256.

[`tools/tests/test_golden.py`](tools/tests/test_golden.py) pins the encoder
on a synthetic clip built in memory, so it does not depend on ffmpeg at all:
stream size, tile count and displayed error, each within 0.5%. Raising the
tolerance from 0.0005 to 0.0007 moves them by 7% to 17%.

## Running an emulator

geolith, through RetroArch, is the first witness: a frame rebuilt from the
cartridge's own bytes matches what it draws pixel for pixel. MAME is a
cross-check only. Its BIOS and configuration defaults have produced failures
and false positives, and it starts full screen on macOS.

- **geolith**: [`tools/scripts/capture_rom.py`](tools/scripts/capture_rom.py)
  loads the geolith libretro core in-process through `fmvcore.libretro`, with
  no window and no RetroArch, and saves the last frame of the run as a PNG.
  `--hold FRAME:BUTTON` presses buttons on chosen frames and `--save FRAME`
  keeps more frames.
- **Against the source**: [`tools/scripts/compare_capture.py`](tools/scripts/compare_capture.py)
  plays the cartridge the same way, decodes the source window the bake used,
  and reports the picture error, the share of torn frames and the lag, with
  the rows under the transport panel left out. On the 6-second Sintel window
  it reads 0.015 Oklab error a frame, 0.0094 blurred, no torn frames and a
  median lag of one frame.
  It boots the Universe BIOS from `~/Documents/RetroArch/system`.
- **MAME**: every scripted run sets `SDL_VIDEODRIVER=dummy` and passes
  `-window -video none -sound none`, as
  [`tools/scripts/verify_mame.sh`](tools/scripts/verify_mame.sh) and the
  cutscene example's `verify.sh` do. `-video none` alone still opens a window on
  macOS.
- **A Neo Geo BIOS** is needed only to run an emulator, never to build, and is
  never committed or downloaded by a script.

## Capture rather than ask

When something is wrong on screen, capture the emulator, cut the recording
into frames and read them. Ask only when that loop has run and cannot settle
the question, and say what it showed.

## The Power of 10, as applied here

| Rule | How it is applied |
|---|---|
| 1. No complex flow | No `goto`, no `setjmp`, no recursion. Dispatch is `switch` |
| 2. Fixed loop bounds | Every loop has a constant or a checked bound. The stream loops are bounded by the frame check below. Recorded exceptions follow |
| 3. No heap | No `malloc` anywhere. All state is static or automatic |
| 4. Short functions | Every function under 30 lines, except a flat `switch` with one line per case |
| 5. Assertions | The library cannot halt the caller's game, so a failed check sets a fault the caller reads: `fmv_faulted` and `FMV_CORRUPT`. The cartridge turns that into a red screen. The checks live in [`src/fmv/guard.c`](src/fmv/guard.c), which the host test suite compiles and calls |
| 6. Smallest scope | File-static where possible. No cross-module globals |
| 7. Check return values | `fmv_play` returns its outcome, and the cartridge tests `fmv_faulted` every frame |
| 8. Sparse preprocessor | Include guards, the `FMV_NO_AUDIO` stubs and the subtitle switch. Recorded below |
| 9. One pointer dereference | Structures are passed by pointer and read one level deep. One function pointer, recorded below |
| 10. All warnings on | `-Wall -Wextra -Werror` on every compile, plus cppcheck in `make analyse` |

### Recorded exceptions to rule 2

- `main()` in `src/player/main.c` runs `for (;;)`. It is the top-level
  scheduler of a program meant to run until the console is switched off.
- `show_fault()` in the same file runs `for (;;)`, kicking the watchdog. A
  corrupt stream is a deliberate halt.
- `wait_vblank()` in `src/fmv/hw.h` spins on the raster line counter. The
  counter is hardware that always advances, and a stuck one stops the
  watchdog kicks, so the board resets rather than hangs.

### Recorded exceptions to rules 8 and 9

- `FMV_NO_AUDIO` replaces the two audio calls with no-ops, so a caller's own
  Z80 driver keeps the M1 ROM.
- `MOVIE_SUBTITLE_COUNT` compiles the subtitle path out of a film that has
  none, because the generated table is then empty.
- `fmv_options.skip` is a function pointer, so a caller's game decides what
  counts as skipping a cutscene. It is the library's only one.

### A corrupt stream stops the player

Every frame is checked before it is drawn: the run count, and each run's
address and length against the movie's grid and its largest frame. The check
reads only ROM, so `fmv_prepare` runs it for the next frame after the
frame's VRAM writes, where it costs no blanking time. A frame nobody prepared,
such as the landing frame of a seek, is checked inside `apply_frame` instead.
A frame that fails stops the player without writing anything, `fmv_play`
returns `FMV_CORRUPT`, and the cartridge clears the screen and turns the
backdrop red. A movie whose layout the board cannot hold fails in
`fmv_open`, before any register is touched.

## Things that will bite you

- **geolith keeps state between runs.** It writes its NVRAM and memory card
  to the save directory, and a later run boots from them. `capture_rom.py`
  gives every run a fresh one. On a fresh NVRAM the cartridge was still not
  on screen at frame 399 and was at frame 600, so capture at 600 or later.
- **objdump needs `-dr`.** An unlinked `jsr` prints as `jsr 0`, and only the
  relocation names the callee. A static function in another section is
  relocated against the section, such as `.text+0x1a4`.
- **ngdevkit's header defaults the eye-catcher to the BIOS.** Byte `0x114`
  is 0 unless the link sets `rom_eye_catcher_mode`, and the BIOS then draws
  its logo from the cartridge's own tiles, which here are film tiles.
- **The image's python3 runs the timing check.** It has no project
  environment, so the build points `PYTHONPATH` at the submodule, and the
  reader uses only the standard library.
- **A `.neo` stores program ROM byte-swapped.** Patch or read it a word at a
  time with the bytes reversed.
- **Work inside vertical blank is budgeted.** 39 blank lines give 29,952
  cycles. The baker charges 64 cycles a slot, so a keyframe's 280 slots take
  17,920 of them by that model. Anything added inside the write loop comes
  out of what is left.
- `np.argpartition` does not order equal values the same way on x86 and Arm
  NumPy builds, so a tie broken by its order gives one output on this Mac
  and another in CI. Pick a nearest with `np.argmin` and rank with
  `np.argsort(kind="stable")` wherever a tie can change what is baked.

## Run on hardware on 2026-10-17

Each of these had run only in geolith. On 2026-10-17 the owner ran the
current build on a Neo Geo and reported no defect so far. The report did not
itemise each check, so a defect found later on any of them comes back here
with what was seen. The next change to the player is unverified again until it
runs on a board.

| Change | What the run covered |
|---|---|
| The 40-line blanking budget | That the overrun counter stays at zero across a full film |
| Eye-catcher mode 2 | That the stock AES BIOS skips its logo and starts the film |
| The frame check, stop and restart, sound on and off, the fault screen | That playback is unchanged, Start stops on black and restarts, Up mutes, and a corrupt cartridge turns red |
| C and D jump between baked seek points, with C going one point further back inside 120 frames of a point | That each press lands on the keyframe at or before its point, audio follows, and repeated D presses always move forward |

## What is not done

The gaps against the family's requirements are listed in the state section of
[FAMILY.md](FAMILY.md).
