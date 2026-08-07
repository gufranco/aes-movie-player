# Development log

What this project tried, what it measured, and what it rejected. The
[README](README.md) says what the cartridge is and how to build one; this
file is the record of how it got there and why it is shaped the way it is.
It is kept because the failures are the expensive part: every lever below
was paid for once and does not need paying for again.

## Contents

- [A blank screen that was not the library's fault](#a-blank-screen-that-was-not-the-librarys-fault)
- [Three registers that cannot be read](#three-registers-that-cannot-be-read)
- [A verification gate that was guessing](#a-verification-gate-that-was-guessing)
- [One ladder cannot price every film](#one-ladder-cannot-price-every-film)
- [The ladder is a frontier, and now it is checked](#the-ladder-is-a-frontier-and-now-it-is-checked)
- [What did not work](#what-did-not-work)
- [Where the emulators disagree, and who wins](#where-the-emulators-disagree-and-who-wins)
- [It plays on a board](#it-plays-on-a-board)
- [What is left](#what-is-left)
- [Standing rules for this project](#standing-rules-for-this-project)

## A blank screen that was not the library's fault

The integration guide told a developer how to package a cartridge by hand,
and the steps were wrong. The containers take a single program ROM holding
the fixed megabyte followed by every switchable bank, which is how this
repository's own build writes it. An ngdevkit project builds those as two
files. The steps copied the first and never mentioned the second.

The result is a cartridge that boots, plays its soundtrack, and shows a
blank screen, because the movie's command stream was never in it. Every
part looks healthy: the ROM images are all present and correct sizes, the
sound driver is byte-identical to the one that works, and the cartridge
runs to completion and returns to the caller's screen on time.

Two things made this expensive to find.

The acceptance check could not see it. It asserted that the caller's screen
settles after the cutscene and no longer matches any frame of the movie. A
screen that never drew passes both. The check now captures mid-playback and
requires a movie frame to be on screen, which is the assertion whose absence
allowed a broken guide to be called proven.

And the first diagnosis was wrong. The blank was blamed on the audio path,
because the failing run had sound and the working ones did not. The working
ones were also packaged by a different tool, and that was the variable. Six
experiments were run before anyone compared the two cartridges directly, at
which point every ROM region turned out identical and the fault had to be
outside the cartridge. Diffing the artifacts is cheaper than reasoning about
them, and it should have come first.

The steps are gone. The bundle carries a script that assembles the ROM set,
so the part that is easy to get wrong is not asked of anyone.

## Three registers that cannot be read

Splitting the renderer into a library meant it had to give the machine back,
so `fmv_open` saved the LSPC mode, the fix-source latch and the palette-bank
latch, and `fmv_close` wrote them back. That is the obvious shape and it is
wrong: none of the three can be read.

| Register | What a read returns |
|---|---|
| `0x3A001B` fix source, `0x3A001F` palette bank | MAME maps the whole `0x3A0000` range to a handler documented as returning the last word on the bus, "almost always the opcode of the next instruction due to prefetch". geolith has no read case for the range at all |
| `0x3C0006` LSPC mode | The raster line counter. geolith's own comment gives the layout: line counter in bits 15 to 7, the 60/50 Hz flag in bit 3, the auto-animation counter in bits 2 to 0 |

So every movie was writing a prefetched opcode into two latches on its way
out, and a raster-derived word into the register whose high byte is the
auto-animation speed. A caller that never touched those registers still got
them scrambled, which is worse than not restoring them at all.

The fix is to stop pretending. The four values live in `fmv_options` now,
defaulted to what a plain cartridge uses, and `fmv_close` writes what the
caller declared. The requirement changed with it: the library restores the
state you name, not the state it found.

What made this findable was building the acceptance test rather than the
feature. The host tests that came out of it model the latches the way the
board does, with no read path at all, so the original code no longer
compiles against them:

```
fmv.c:217:23: error: use of undeclared identifier 'REG_CRTFIX'
```

A stub that let a read succeed would have let the defect pass.

## A verification gate that was guessing

The MAME check returned 1.5658, 1.5929, 1.5696 and 27.8718 on four
consecutive runs of a cartridge that had not changed. The last one is a
failure, and any of them would have been reported as the number.

Two separate causes, one found and one only cornered.

The matcher took the best-scoring frame by `argmin` and reported it with no
measure of how much better it was than the next. A movie repeats each source
frame about two and a half times and holds still for long stretches, so
several frames score within noise of each other. `measure_drift.py` already
carried a guard for exactly this; the tool the build gate runs did not. It
now sets aside the run of identically scoring frames around the best, finds
the closest genuine rival, and refuses rather than choosing when the margin
is under `--min-separation`. On the reference clip the match wins by 7.83 of
255.

The capture itself was also varying. Giving MAME a real render target with
`-window -nomaximize` stopped it, and twenty-odd consecutive runs have agreed
since, against four different readings in four before. That is evidence, not
a mechanism, and it is recorded as such: the emulation is deterministic, so
what varied was which rendered frame reached the snapshot, and no reading of
MAME's source has been done to confirm it.

## One ladder cannot price every film

The rungs are priced by a single table of relative costs, and measurement says
that table cannot be right for everything. What a colour reduction saves
depends on what is on screen, and it varies enough to swamp the ladder.

Four rungs, baked on the animated reference film and on a grainy live-action
broadcast sequence, each cost expressed against `q01` on the same clip:

| Rung | Animation | Live action | What the ladder says |
|:-----|----------:|------------:|---------------------:|
| `q01` | 1.000 | 1.000 | 1.000 |
| `q09` | 0.620 | 0.895 | 0.809 |
| `q17` | 0.426 | 0.752 | 0.654 |
| `q25` | 0.297 | 0.557 | 0.489 |

The ladder sits between the two, which means it is wrong in both directions at
once. On animation it charges 53% more for `q17` than the rung actually costs,
so the plan promises less runtime than the cartridge has and picks a lower rung
than it needs to. On live action it charges 13% less than the rung costs, so
the plan promises runtime that is not there.

The reason is visible in the mechanism. Cheaper rungs save by letting more
tiles quantise alike, and film grain perturbs almost every tile whatever the
palette precision, so there is far less to collapse. The saving is a property
of the content, not of the setting.

Two things follow. `--quality auto` says this about itself now, in the plan it
prints, rather than presenting a number it cannot support. And a bake that
overruns fails instead of shipping a cartridge that silently stops tracking the
source, so the optimistic direction costs a wasted bake rather than a bad cart.

The measured path has none of this problem. `--quality search` bakes from `q01`
down and takes the first rung that fits, so it never consults the table at all.

## The ladder is a frontier, and now it is checked

The claim above, that no rung costs as much as another while looking no
better, went untested for most of this project's life.
[`sweep_ladder.py`](tools/scripts/sweep_ladder.py) bakes one window at every
reachable rung and checks it. Each bake gets the whole tile budget for a short
window so the rate controller never engages and every rung reports its natural
cost rather than what a controller squeezed it into.

On a 45 second window, 34 rungs measured: cost falls monotonically, error
rises monotonically, and **no rung is dominated**. The claim holds.

The same sweep found two defects that the declared costs had been hiding.

**The frame-hold rungs were costed optimistically.** Calibration anchors the
ladder onto the source's own cost curve, and all three anchors were chroma
values at hold 1, so the hold rungs were extrapolated rather than measured.
Every chroma rung came out conservative by 2% to 9%, which is the safe
direction. Every hold rung came out optimistic:

| Tier | Planner implied | Measured | Planner was |
|---|---:|---:|---|
| q30 | 0.652 | 0.618 | 5.1% conservative |
| q32 | 0.521 | 0.568 | 9.0% optimistic |
| q33 | 0.444 | 0.503 | 13.3% optimistic |
| q34 | 0.395 | 0.480 | 21.6% optimistic |
| q35 | 0.350 | 0.441 | 26.0% optimistic |

Optimistic is the direction that hurts: the planner promises runtime the
cartridge cannot hold, the dictionary reaches its cap, and the last minutes
freeze. A fourth anchor now sits on a hold rung, so that range is measured
rather than guessed. It is skipped on a source too slow for the hold to drop
any frame, where it would measure nothing.

**A rung was being offered that could never be baked.** For a 24 fps source
`q31` holds each frame for two refreshes, which still shows every frame the
source had, so it saves no tiles and the baker refuses it outright. The
planner listed it as fitting anyway. `survey` and `select` now take the
source's frame rate and leave out rungs the baker would refuse.

Correcting both moved the choice for the reference film from `q17` to `q16`
without trimming a second.

**The exchange rate is not uniform, and that is what sets the step count.**
Measured across the ladder, a step at the top saves about 4,100 tiles for
0.00001 error, while a step at the bottom saves about 1,900 for 0.00026: a
65x spread. Steps near `q01` are nearly free in quality, steps near `q30`
are not. A ladder with uniform percentage steps would be too fine at the top,
where nothing visible changes, and too coarse at the bottom, where each step
costs the most.

**Calibration accuracy comes from window count, not sample length.** A
feature varies enormously in difficulty from scene to scene, so a handful of
windows lands wherever it happens to land. Measured against a known full
bake, 3 windows read 0.62 times the true rate, 6 read 1.58, and 12 read
0.91, while total sampled time barely mattered. Coverage of the content is
what converges. The default of 24 short windows lands within a percent, for
72 seconds of sampling.

<details>
<summary><strong>Per-scene palettes, rate control, and colour</strong></summary>

<br>

## What did not work

Negative results, kept because they cost real time to find.

**Frame blending.** The error metric ranked it the strongest lever
available, cutting error from 23.33 to 9.11 at a fixed frame hold. On the
cartridge it reads as a smear and was rejected on sight. The metric scores a
blended frame as closer to the source sequence, because an average of the
surrounding frames genuinely is closer by that measure than a stale frame
is, while the eye reads the same average as an artifact. Removing it made
the picture sharper *and* the movie slightly longer, since the blend was
adding tiles.

**Motion masking.** Raising the error budget where the picture moves is
sound in a codec with residuals, and is roughly what Angel Studios did by
degrading backgrounds in busy scenes. Across factors from 20 to 3000 the
tile count here did not move by one entry while error rose fourfold. A
deferred correction still has to point at a tile, so the tile is interned
later regardless, just against a picture that has drifted further.

**A narrower raster.** Real cartridges run 304 or 288 pixels wide instead of
320, and dropping 32 columns removes a tenth of the slots, so a tenth of the
tile budget looked like it should come back. Blanking the outer 16 pixels on
each side of a 40 second window moved the tile count from 35,136 to 35,779:
it went *up*. Blanking the same 32 pixels down the middle instead took it to
30,098. The same area is worth 14% of the dictionary in the centre and less
than nothing at the edges, because cost follows novel detail and framing puts
the detail in the middle. A narrower raster buys a smaller picture and no
budget, so width stays at 320.

**Flip deduplication.** 67 saved tiles out of 81,044. Exact 16x16 mirrors
essentially do not occur in photographed or rendered material.

**Compressing the command stream, and auto-animation.** Both save stream
bytes. The stream used 4.5 MB of 8 MiB, so stream bytes are not scarce.

**Palette-only fades.** Across a whole movie, 35.7% of frames change at all
and only 4.6% of those are explained by a single global brightness scale.

**Sprite-position motion compensation.** The grid tiles the raster, so
moving a sprite shifts a whole 16 pixel column, and content almost never
pans by exactly one tile.

**Near-duplicate merging in the dictionary.** The obvious attack on the
binding constraint, and it does not pay. At thresholds fine enough to be
imperceptible it collapses 1 to 3% of the dictionary; only signatures coarse
enough to visibly destroy detail reach 48%. Tiles genuinely differ.

**A richer tier than `q17` on this film.** Every rung is a row of settings
rather than something to build, and all 34 reachable ones bake, so this was
only ever a question of which to ship. Baked full length, `q16` fits easily
at 82% of the C-ROM with the dictionary never full, and returns nothing for
it: `displayed_error` is identical to six decimals and `mean_error` is 4.9%
worse, for 12,697 more tiles.

The reason is the rate controller rather than the cartridge. Its multiplier
is capped at 4096, and `q16` pinned it there while `q17` peaked at 314. The
richer tier spends faster, the controller ratchets up to compensate, runs out
of room to tighten, and hands back later exactly what the tier bought early.
With 18% of the C-ROM still free, the binding constraint at the top of the
ladder is the controller's ceiling, not character ROM.

**Dithering the source before quantisation.** No measurable effect, because
the banding comes from the 15 colours a tile may use rather than from the
15-bit colour word. Dithering inside palette assignment would be the real
lever and has not been built.

Two measurement traps also worth recording. Counting the *number* of slots
that differ is useless as a scene-cut test on photographed material, where
grain perturbs nearly every slot every frame: it fired on 22% of all frames,
and each false cut rewrote all 280 slots. And a metric that averages the
error of tiles the encoder *wrote* improves whenever the encoder skips more
work, so it rewards doing less; the fidelity number here charges every slot
of every frame against the true source frame instead.

### Ordered dithering, which costs nothing and changes nothing

Gradient blocking is visible on flat areas, and dithering the source before
quantisation does nothing about it, because the banding comes from the fifteen
colours a tile may use rather than from the colour word. Dithering where pixels
are matched to a palette is the version that could work, and the dictionary
rules out the obvious form of it. Error diffusion makes a tile's output depend
on its neighbours, so two identical source tiles stop quantising alike and stop
interning as one, which spends the C-ROM the whole design is short of.

An ordered threshold has neither problem. The matrix is 8x8 and a tile is
16x16, so the field depends only on where a pixel sits inside its own tile and
still runs continuously across tile boundaries. It is built as a second-nearest
palette entry and a blend fraction beside the nearest one already precomputed
per palette and colour, and it is live behind `--dither`.

The interning worry was unfounded, and measurably so. On a 30-second window at
`q17` the dictionary moved from 54,250 tiles to 54,192, which is 0.11% and in
the cheaper direction. Identical tiles still collapse to one entry, which the
tests pin directly rather than inferring from the count.

It also does not help. Per-pixel error rose 0.6% and `displayed_error` rose
12.3%, which is what a metric that ranks noise harshly is expected to say about
added noise and is not on its own a verdict. The verdict is that at 7x zoom on
the closing card and on the opening sky, the dithered and undithered frames are
not distinguishable. The reason is visible in the mechanism: palettes are
refitted every epoch against the tiles actually on screen, so in a flat region
the nearest entry is already close, the blend fraction sits near zero, and the
threshold almost never fires. The dither has little left to do because the
palette fitting already did it.

So it ships off. The flag stays because the cost is zero and a source with
harsher gradients than this one may yet want it, but nothing here argues for
turning it on, and a knob that is on by default should have evidence behind it.

## Where the emulators disagree, and who wins

- **Program-ROM banking.** MAME masks the bank register with `0x07`, giving
  8 banks of 1 MiB, which matches the three-bit latch on the board. geolith
  derives its mask from the ROM size and allows up to 8 bits. A stream
  needing more than 8 banks works in geolith and reads the wrong bank on
  hardware, so the baker enforces MAME's limit.
- **C-ROM banking does not exist**, as the ceilings table above records.
  Both emulators agree by omission: neither implements it on any board.

</details>

<details>
<summary><strong>Prior art the design draws on</strong></summary>

<br>

- **Resident Evil 2 on the Nintendo 64.** Angel Studios fit a two-CD, 1.2 GB
  game into 64 MiB with 15 minutes of video in a 24 MiB budget, a 165:1
  ratio, decoded in software with no video hardware. Chroma subsampling is
  the technique this project inherits, as the chroma weight on the shared
  Oklab metric.
  [Modern Vintage Gamer](https://www.youtube.com/watch?v=BaX5YUZ5FLk),
  [Hackaday](https://hackaday.com/2026/02/03/how-resident-evil-2-for-the-n64-kept-its-fmv-cutscenes/),
  [Angel Studios postmortem](https://www.gamedeveloper.com/programming/postmortem-angel-studios-i-resident-evil-2-i-n64-version-)
- **RoQ**, used by The 11th Hour and Quake III: a motion-compensating vector
  quantizer with per-frame codebooks capped at 256 entries, so a bounded
  number of new fragments enter per frame. This is the shape of the baker's
  tile dictionary with a per-frame cap.
  [MultimediaWiki](https://wiki.multimedia.cx/index.php/RoQ)
- **Bad Apple on the Neo Geo** by HPMAN: 320x224, 13,167 frames, about four
  minutes in roughly 3 MB. One bit and one palette, so tile dedup is
  best-case, but it proves tile-streamed video with synced audio on real
  hardware. [yAronet](https://www.yaronet.com/topics/188010-bad-apple-demo-datlibdatimageneosoundbuilder)

</details>

## It plays on a board

The build carrying both of this session's timing fixes has run from a NeoSD
flash cart on a real AES and a real MVS, full length, with no defect seen.
That closes the question the project could not answer for its whole life, and
it is written up with its limits under
[On real hardware](README.md#on-real-hardware).

## What is left

Nothing on the list. Gradient blocking was the last entry and it is now
answered, though not the way the entry expected. What the ordered threshold
turned out to be is written up under [What did not work](#what-did-not-work).

## Standing rules for this project

Requests that outlive any single change.

- **Nothing hardcoded that the source can decide.** Hardware limits are
  fixed; anything else is measured. The audit of which is which is under
  [The quality system](README.md#the-quality-system), and the values the current bake
  derived are in the table above.
- **The code never trims.** Shortening a film is the owner's decision and
  not the baker's. A source that fits nowhere is refused with the exact
  figure that would have to come out, and a source too long for the voice
  ROM gives up sample rate rather than its tail. No path shortens a movie
  to make it fit, and tests hold that.
- **Extract the maximum quality the hardware allows,** losing only what a
  viewer cannot perceive. Every lever that was tried and failed is under
  [What did not work](#what-did-not-work), so it is not tried twice.
- **Give the decision to the operator.** The plan prints every rung with its
  exact overshoot so trimming stays a choice made with numbers in view.
- **Motion blur stays out.** Revisiting it was considered and declined. It
  cannot help the blocking, which has spatial causes, and blending at full
  frame rate reads as a smear. The only defensible case would be shutter
  blending at `frame_hold > 1`, which no current bake uses.
- **Judge picture quality by eye, not by the metric.** `displayed_error`
  ranked frame blending the strongest lever available and it looked awful on
  the cartridge. Numbers decide cost; a person decides quality.
- **Verify deep frames from the on-screen counters.** See the warning about
  `measure_drift.py` above. Reporting a regression that a stale capture
  invented happened twice in one session.
