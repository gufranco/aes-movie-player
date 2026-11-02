# Why the baker is shaped as it is

These notes explain why each baker module, script and test is shaped as it is.
They were the docstrings and comments in the source, which the project's rules keep out of code.

## The baker

### [`neogeomedia/__init__.py`](neogeomedia/__init__.py)

Offline baker for the Neo Geo media player.


### [`neogeomedia/adpcmb.py`](neogeomedia/adpcmb.py)

Encode mono audio into the YM2610's ADPCM-B format.

The algorithm is the one ymfm implements in `adpcm_b_channel_clock`,
which is the decoder geolith runs and the reference MAME shares. Each
4-bit nibble carries a sign in bit 3 and a magnitude in bits 2 to 0, the
predictor moves by `(2 * magnitude + 1) * step / 8`, and the step is
then scaled by `[57, 57, 57, 57, 77, 102, 128, 153] / 64` and clamped to
the range 127 to 24576. The predictor starts at zero with the smallest
step. The high nibble of a byte is played first.

The encoder is closed-loop: it runs the decoder's own state machine and
picks, for each sample, the nibble whose resulting predictor lands
nearest the target. Choosing greedily against the real decoder state is
what keeps quantization error from accumulating, and it means the
encoder cannot drift away from what the chip will produce.

ADPCM-B addresses are in 256-byte pages, so the payload is padded to a
page boundary and the start and end registers hold page numbers. Padding
uses 0x08 rather than 0x00 because there is no zero delta in this
format: the smallest magnitude still moves the predictor, so a run of
0x00 ramps steadily to full scale. 0x08 pairs a positive step with a
negative one and stays put, which keeps the tail of the ROM quiet if the
end address is ever overshot.

#### `start_address`

Start register value, in 256-byte pages.

#### `end_address`

End register value, in 256-byte pages, inclusive.

#### `delta_n_for`

Rate register for a target sample rate.

ymfm advances a 16-bit accumulator by this value each chip sample
and consumes a nibble when it passes 0x10000, so the divisor is
65536 rather than the 65535 the hardware notes quote.

#### `exact_rate`

Sample rate produced by a rate register value, without rounding.

#### `rate_below`

The nearest playable rate at or under a wanted one.

`delta_n_for` rounds to the nearest step, which can land above the
caller's ceiling. Flooring onto the grid keeps a rate that has to
fit inside a budget from quietly exceeding it.

#### `rate_for`

Sample rate produced by a rate register value.

#### `encode`

Encode 16-bit mono samples into ADPCM-B nibbles.

#### `build_rom`

Lay the encoded payload out as the ADPCM-B voice ROM.

#### `decode`

Run the same state machine forward over a payload to recover the samples the
chip would play. It is the inverse of `encode`: it unpacks each byte high nibble
first, moves and clamps the predictor by the same step and scale, and returns
the first `sample_count` samples. It exists so a measurement can hear what was
baked rather than trust the encoder, and it reproduces the encoder's own landed
predictor values exactly, so a round trip is the chip's output, not an
independent approximation of it.


### [`neogeomedia/bake.py`](neogeomedia/bake.py)

Drive the bake passes and report what the movie costs in ROM.

Writes the cart-side artifacts under `build/baked/` and the generated
sources under `build/generated/`.

#### `self_tier_name`

The rung this cart was baked at, for the overlay to display.

#### `BakeRequest`

Sample rate for the voice ROM, or None to take the highest that fits.

There is no sensible constant here. The ceiling is the chip's, the floor
is however slow the sample has to run to end on an addressable page, and
which of the two applies depends entirely on how long the movie is.

#### `report`

Sizes measured on this clip and what they project to.

A fact both players report carries the name the Master System player
gives it: `banks`, `bytes`, `fps`, `dither`, `bars`, `displayed_error`.
The figures only this player has, such as `tile_count` and the
projections, keep their own names.

#### `write_movie_bundle`

Emit the drop-in folder for a bake that has already run.

Every number the bundle states about the movie comes from the bake
that produced it rather than from a second measurement, so the guide
and the generated header cannot disagree about what the movie costs.

#### `run`

Decode, encode, and write every cart artifact.

#### `_overran`

Whether the encoder ran out of room rather than finishing the film.
A bake that overran writes no `--bundle`, so no game can ship a film
that stops tracking its source.

Rate control degrades quality to stay inside the budget, and that is
the healthy path. When even its ceiling is not enough the dictionary
fills, every later frame stops interning new tiles, and the picture
quietly stops tracking the source. That has to be a failure: the
build otherwise succeeds and the cartridge looks finished.


### [`neogeomedia/bakeargs.py`](neogeomedia/bakeargs.py)

Read the bake's command line and settle every value it leaves open.

How much of the source to profile. Long enough to see several cuts.

#### `resolve_quality`

Pick the tier.

A rung is named or it is not chosen here. Estimating one from a
sample was measured to be wrong in both directions and cannot be
fixed, because what a colour reduction saves depends on the content
rather than on the setting. The cartridge tool settles it by baking;
`neogeomedia.plan` prints the estimate for a human to look at.

#### `pick`

An explicit flag wins, then the tier, then the built-in default.

#### `resolve_frame_hold`

Turn a wanted frame rate into a hold, and reject a hold that does nothing.

A hold counts display refreshes while the interesting quantity is
source frames, so the two only agree when the source runs at the
raster rate. Asking for 30 fps from a 24 fps source picks a hold of
2, which skips no source frame and buys no tiles while still
costing temporal accuracy. That is worth an error rather than a
silent no-op.


### [`neogeomedia/blobs.py`](neogeomedia/blobs.py)

Build the cart-side binary blobs a bake writes under `build/baked/`.

The character ROM halves are written at the dictionary's own length with
no padding. A sprite ROM is a flat array of tiles, so a caller appending
its own writes them straight after the movie's, and whoever assembles
the cartridge pads to the power of two the hardware needs.

#### `palette_blob`

Every epoch's CRAM words, back to back in playing order.

#### `subtitle_blob`

Cues from the sidecar beside the source, or nothing when there is none.

Timings are absolute in the file, so the baked window has to be shifted
to the front and anything outside it dropped: a cue at 20 minutes means
nothing to a cartridge holding minutes three to five.

#### `epoch_blob`

The frame each epoch begins on.

The half it lives in is not stored, because it alternates: an epoch
occupies the half its index parity names, which is what lets the
next set be written while the current one is still being read.


### [`neogeomedia/bundle.py`](neogeomedia/bundle.py)

Emit a folder a game project drops in to get a movie into its cart.

Everything ships as source. The library is copied rather than installed,
so the copy a developer holds is pinned to the bake that produced it,
and a mismatch between the two announces itself at compile time instead
of misbehaving at runtime.

The layout mirrors what an ngdevkit project already looks like: source
under one directory, generated data under another, and a make fragment
to include. Nothing here reaches outside the emitted folder, so dropping
it in touches only files the developer owns.

The video path. `fmv.h` is the only header a caller includes.

The reference Z80 driver, which a caller hosts or replaces.

Cartridge packagers that can express an ADPCM-B ROM.

ngdevkit's own romtool declares every voice ROM as ADPCM-A, and
MAME allocates a delta-T region only when a software list names
`ymsnd:adpcmb`, so a soundtrack packaged that way is silent. These
two are standard-library only and travel with the bundle.

#### `rom_image_size`

Round a payload up to a size a Neo Geo ROM image may take.

Every ROM in a cartridge is a power of two, because the hardware
masks an address with a mask derived from the size. A payload that
lands anywhere else is padded by whoever assembles the cartridge.

#### `write_bundle`

Write the drop-in folder and return where each part landed.


### [`neogeomedia/calibrate.py`](neogeomedia/calibrate.py)

Measure what a source costs per minute before committing to a bake.

The tile rate is a property of the content: a scene of two people
talking reuses its dictionary heavily, while dense animation refuses to.
A ladder that guessed from running time alone would be wrong in both
directions, so the rate is measured here on the source itself and the
ladder is positioned against it.

Sampling several short windows spread across the source beats measuring
one contiguous stretch, because a single window sees one scene and one
palette. The windows are then encoded as a single clip so the dictionary
reuse between them is counted, which is what a full bake would get.

Accuracy is governed by how many windows there are, not by how long
they are. A feature varies enormously in difficulty from scene to
scene, so a handful of windows lands wherever it happens to land.
Measured against a known full bake, 3 windows read 0.62 times the true
rate, 6 read 1.58, and 12 read 0.91, while the total sampled time
barely mattered. Coverage of the content is what converges, and at 24
windows the estimate lands within a percent, which is why the default
is many short windows rather than a few long ones.

#### `sample_windows`

Evenly spread, non-overlapping windows across a source.

A source too short to hold one window is measured whole, which is
both the honest answer and the cheap one.

#### `measure_reference_rate`

Tiles per minute this source costs at the reference tier.

The windows land inside the stretch that will actually be baked. A
bake of one segment measured against the whole film would be
calibrated on content it is never going to encode.

#### `measure_anchors`

Measure this source's own cost curve, not just one point on it.

Returns the reference rate and a map from the ladder's averaged relative
cost to what this source actually costs there. One measurement fixes the
scale; the anchors either side fix the shape, which the ladder cannot
know because it varies with the content.

The clip is decoded once and encoded three times, so the extra accuracy
costs two encodes rather than two decodes.


### [`neogeomedia/cartridge.py`](neogeomedia/cartridge.py)

Turn a movie file into a cartridge with one command.

The baker and the ROM build are separate tools because they answer
separate questions, but the common case is neither: it is someone with a
video file who wants a cartridge out the other end. This runs the whole
path, chooses the quality tier by measuring the source, and takes the
subtitle file by name rather than insisting it sit beside the movie
under a matching name.

#### `_measured_tier`

Resolve a tier by baking rather than by sampling, remembering the result.

#### `_reach`

How much of the film a rung holds, measured by a bake that stops when
the cartridge is full. A refusal turns it into the `--duration` that
would fit, through [`shortfall.py`](neogeomedia/shortfall.py), and never
trims the film itself.

Every bake writes `report.json`, a refused one included, so the figures
of a film that did not fit are still on disk to read.


### [`neogeomedia/codegen.py`](neogeomedia/codegen.py)

Write the generated C and assembly sources a bake links against.

Blobs reach the ROM through `.incbin` in an assembly stub rather than as
C arrays. Measured on this toolchain, a C array costs about five times
its own size in source text and 0.4 seconds per 256 KiB; the tables
alone would be tolerable either way, and the character ROM would not,
since it never passes through the compiler at all and turning it into
source would mean compiling it only to extract the same bytes back out.

The stub names those blobs by filename alone and leaves the assembler
to find them on its include path, so the build passes `-I` for the baked
directory. Writing the path the baker happened to use would pin the
sources to one machine, and a bake taken from anywhere but the build
tree would fail to assemble.

Link-time byte offset of the stream inside the switchable window.

The value arrives through `--defsym` at link time rather than baked in,
because which switchable bank the stream starts at is decided by the
project doing the linking. A cartridge whose banks are otherwise empty
starts it at zero; a game that already banks code of its own moves it up
without re-baking anything.

File-name stem of the per-bank stubs.

ngdevkit's linkscript keeps every object whose file name contains
`__bank` out of the fixed megabyte and gathers it into `.text2`, which
the cartridge rules turn into one switchable bank. The doubled
underscore is the convention, not a typo.

What one slot update costs in `apply_frame`'s inner loop.

Read off the compiled loop rather than assumed, six instructions in all:
12 for the port address
reload, 12 and 16 for the two data writes, 8 for the pointer bump, 6 for
the compare and 10 for the taken branch. It counts the per-tile loop
only. A frame also pays a setup per run, twenty of them on a full
keyframe, so a budget taken from this is a floor rather than a ceiling.

#### `baker_version`

Major and minor of the installed baker, for the bundle stamp.

Patch releases are left out of the comparison deliberately. The
stamp exists to catch a bundle whose library and movie data drifted
apart, and a patch that fixes a bake without moving the data layout
is not that.

#### `write_stream_banks`

One `__bank`-named stub per switchable bank the stream occupies.

The stream is far larger than the single megabyte the linkscript
gives to the switchable window, so it cannot be one object. Slicing
it at bank boundaries costs nothing, because the encoder already
pads every frame record forward rather than letting one straddle a
boundary, and it gives the toolchain the one shape it can place:
a bank is an object, and an object is a link.


### [`neogeomedia/content.py`](neogeomedia/content.py)

Measure the properties of a source that change what a good bake looks like.

Geometry analysis lives in `frames`, because a bake cannot proceed without
it. What is measured here is different: nothing breaks if it is skipped, but
the numbers say which settings are safe on this particular material.

Two measurements, each tied to one decision:

- Saturation, from `signalstats`. Colour weight is charged against the a and
  b axes of the metric, so on washed-out material a low weight costs little
  and on vivid material it costs a lot.
- Movement, from the source's own frame-to-frame slot distances. What counts
  as "this slot moved" decides when a scene cut fires, and a fixed threshold
  is not portable: 0.01 flagged 1% of slots on one film and 22% on another,
  so cut detection meant something different on each. Taking a high
  percentile of the movement the source actually shows makes it mean the
  same thing everywhere.
- Scene cuts, from `scdet`. Palettes are fitted per epoch, and an epoch that
  spans a cut has to serve two scenes with one set of colours.

Grain is deliberately absent. Two candidates were tried and both measured
high-frequency content rather than noise: chroma bitplane noise called a
pristine 720p capture grainier than a synthetic clip built out of noise, and
comparing a source against a temporally denoised copy ranked the noisy clip
as the cleaner of the two, because motion moves that measure further than
grain does. A grain number that fires on detail would argue for denoising the
very texture the dictionary exists to carry, so none is reported.

Where the "this slot moved" line is drawn in the source's own movement.

A cut moves nearly every slot, while ordinary motion inside a scene moves
few. Setting the line at the 99th percentile leaves about one slot in a
hundred above it during ordinary motion, which is a wide margin against the
fraction a cut has to clear. On the movie this project was built against,
the measured value comes out at 0.0099, which is the constant the parameter
used to be fixed at: that default was this source's own answer all along.

A floor of exactly zero would call every rounding difference a movement.

#### `ContentProfile`

What the source is made of, as far as ffmpeg can tell.

#### `_metadata_values`

Run a filter that prints metadata and collect one key from it.

#### `measure`

Profile a source without decoding it into the encoder.

#### `epoch_seconds_for`

How long a palette epoch should last on material that cuts this often.

An epoch spanning a cut serves two scenes from one set of colours, so
the cadence tracks the cut rate. It is bounded at both ends: the loader
needs frames to upload the next set, and an epoch long enough to cover a
whole reel stops being per-scene at all.

#### `movement_floor`

How far a slot has to move on this source before it counts as moved.


### [`neogeomedia/crom.py`](neogeomedia/crom.py)

Pack 16x16 4bpp tiles into Neo Geo C-ROM byte pairs.

Adapted from `pack_bitmap_to_tiles` in the DoomNG
`tools/doomng_build/bake/crom.py`, which packs a whole atlas
column-major. The dictionary here has no spatial layout, so this version
packs one independent tile per entry and vectorizes across the batch,
since a feature-length dictionary runs to hundreds of thousands of
tiles.

The byte layout is the one geolith's `geo_lspc_tpix` reads. A tile is
128 bytes in the interleaved C-ROM, where even bytes come from c1 and
odd bytes from c2. Within a tile, columns 8 to 15 occupy the first 64
bytes and columns 0 to 7 the last 64. Each pixel row is four
interleaved bytes, two from each ROM, holding bitplanes 0 and 1 in c1
and bitplanes 2 and 3 in c2. Bit `n` of a byte is the pixel at column
`n` of the eight-column half, so the leftmost displayed pixel is the
least significant bit.

#### `pack_tiles`

Pack a batch of 16x16 nibble tiles into per-ROM byte arrays.

#### `rom_size_for`

Per-ROM byte size for a dictionary, rounded to a power of two.

geolith masks the tile number with a mask derived from the C-ROM
size and then takes the byte offset modulo that size, so a
non-power-of-two ROM aliases high tile numbers onto low ones. Padding
to a power of two makes the mask exact.

#### `build_rom_images`

Pack a dictionary and pad both ROM images to their final size.

#### `unpack_tiles`

Recover nibble tiles from their packed ROM bytes.

The inverse of `pack_tiles`, used to check stored tiles against the
source. The ROM itself never needs this.


### [`neogeomedia/dictionary.py`](neogeomedia/dictionary.py)

Global tile dictionary, sized for a cart filled to the C-ROM ceiling.

A full cart holds 1,048,576 tiles, the whole span of the 20-bit tile
number, so this has to stay compact at a million entries. Tiles are kept
in their packed C-ROM form, 64 bytes in each ROM half, and the lookup is
keyed by a 128-bit digest of those bytes rather than by the bytes
themselves. Storing full keys would cost more than the tile data.

Flip deduplication is off by default. It was measured on real footage at
67 saved tiles out of 81,044, under a tenth of a percent, because exact
16x16 mirrors essentially do not occur in photographed or rendered
material. Leaving it on would quadruple the lookup for that.

When the dictionary fills, `intern_batch` reports no reference for
further new tiles rather than raising. A movie longer than the cart can
hold should degrade by leaving those slots showing their previous tile,
not by failing the bake outright.

#### `TileDictionary`

Interns packed 16x16 nibble tiles, optionally collapsing mirrors.

#### `is_full`

True once the tile number has no room left.

#### `reseed`

Stop sharing entries with earlier epochs.

A tile holds palette indices, not colours, so one interned while
a given bank held one epoch's colours draws wrong once that bank
holds another's. Salting the key retires every earlier entry
without discarding the bytes already written to the ROM. Measured
on real footage, scenes share about 0.1% of their tiles, so the
cost of giving that up is close to nothing.

#### `intern_batch`

Intern a batch of patterns, packing them in one pass.

#### `intern`

Intern one pattern, rejecting anything the packer would reject.

#### `payload_bytes`

Length of the dictionary itself, before any padding.

A C-ROM is a flat array of tiles, so a caller appending its own
after the movie's writes them at this offset and its first tile
takes the number this dictionary stops at.

#### `rom_images`

The two C-ROM halves, padded to their final size.

#### `tiles`

Unpack the stored patterns, for verification rather than for the ROM.


### [`neogeomedia/encode.py`](neogeomedia/encode.py)

Turn vblank-rate frames into a tile dictionary and a command stream.

The encoder walks the clip one frame at a time holding a model of what
the LSPC currently shows. A slot is only touched when its source content
changed since the previous frame and the change is large enough to see,
which is what makes a 24 fps source cheap at the 59 Hz refresh: every
repeated source frame leaves all 280 slots alone and costs two bytes.

Keyframes rewrite all 280 slots whether or not they changed. That is
what makes them random-access entry points for the transport controls,
so the cost is deliberate. A keyframe also fires on a scene cut, where
most of the frame changed anyway and a delta would be no cheaper.

There is no framebuffer on this hardware, so there are no additive
residuals. Every correction resolves to pointing a slot at some tile
that exists in the dictionary, which means residual precision is
dictionary richness is C-ROM.

#### `to_tiles`

Split frames of color indices into a (frame, row, col, y, x) grid.

#### `from_tiles`

Reassemble one grid of tiles into a full frame.

#### `_new_dictionary`

The dictionary this encode may fill, capped by any tile budget.

Capping here rather than in the controller is what makes the budget
a guarantee: no threshold can be raised high enough to slow some
content down, but a dictionary that refuses to grow always holds.

#### `_tile_frames`

Yield one frame's tile grid at a time from chunks of RGB frames.

#### `_Totals`

Running counters the encode loop accumulates across frames.

#### `track_tolerance`

Record the highest budget the controller had to reach.

#### `encode`

Encode a whole in-memory clip. Convenience wrapper over `encode_stream`.

#### `_build_palette_sets`

One palette set per epoch, alternating between the two CRAM halves.

Colours refitted per scene score around a tenth better than a single
set stretched over a whole feature, but the new set has to reach CRAM
before the scene it belongs to appears. Alternating halves buys that
time: the next epoch is written into the half nobody is reading while
the current one is still on screen.

A movie with one epoch has nothing to alternate with, so it keeps the
whole allocation. Halving it there would give up half the colours to
buy time nobody needs.

#### `_enter_epoch`

Move the encoder onto a new epoch's colours.

#### `_advance_epoch`

Move onto the next palette epoch once this frame has reached it.

#### `_render_buffer`

Somewhere to keep every rendered frame, when the caller wants them.

#### `_should_stop`

Whether a probe bake has learned everything it can.

#### `_out_of_room`

Whether this bake can no longer finish inside its budget.

Once the dictionary is full or the budget is spent, every later frame
stops interning new tiles and the picture stops tracking the source.
Nothing after that point can change the verdict, so a probe bake has
no reason to keep decoding.

#### `_record_frame`

Score this frame and hand the picture to whoever wants it.

#### `encode_stream`

Encode frames as they arrive, holding only two frames at a time.

A cart filled to the character-ROM ceiling is around 15,600 frames.
Neither the source nor the rendered output fits in memory at that
length, so the palette set is fitted from a strided sample taken in
an earlier pass and the frames themselves stream past.

#### `_Encoder`

The state one encode carries from frame to frame, and the step that advances it.

Each call to `step` takes one decoded frame through the same order every
time: hold, epoch, keyframe decision, rate control, slot selection, palette
assignment, interning and recording. Keeping that order in one place is what
lets the stream, the dictionary and the statistics agree.


### [`neogeomedia/epochs.py`](neogeomedia/epochs.py)

Decide where palette epochs begin and which tiles each one is fitted from.

How many colour words the player uploads per frame.

The figure is a vblank budget rather than a preference, and the baker has to
agree with it: an epoch shorter than the upload of the one after it shows a
half-written palette. It is emitted into the header so the player reads this
value rather than keeping a second copy of it.

How many upload times an epoch must last.

One would be the bare minimum and would leave nothing for the frames where
the transport or the diagnostics page is also writing to the fix layer.

How many frames each epoch's palettes are fitted from.

This is the quantity that decides palette quality, so it is the one worth
holding steady. Fixing the stride instead let it drift with the epoch
length, which is measured from the source and therefore varies per film.

#### `stride_for_epoch`

Sample every nth frame, so an epoch contributes about the target count.

#### `thin_sample`

Cap how many tiles the palette fit sees.

Fitting the palette set materializes an Oklab triple per pixel of
every sample tile. On a full-length clip the strided sample runs to
over half a million tiles, which is gigabytes of float before the
encoder has started. A capped random subset picks the same palettes
for a fraction of the memory.

#### `epoch_upload_frames`

Frames the player needs to make one epoch's colours resident.

Epochs alternate between the two halves of the video palette allocation,
so a set is half the palettes, and the upload runs at a fixed number of
words per frame. Computing it here keeps the baker and the player from
disagreeing about a number that, if they do, shows a half-written palette
on screen.

#### `epoch_starts`

Where epochs begin: at scene cuts, falling back to a fixed cadence.

A bucket that straddles a cut has to carry colours for both sides of
it, which is the thing per-scene palettes exist to avoid. Starting
each epoch at a real cut measured 4% less error and 1.7% fewer tiles
than an even split. Cuts further apart than the cadence are still
subdivided, so a long static scene does not become one huge epoch.

An epoch has to last long enough for the player to write the next

one into the other half of CRAM, a slice at a time. Any boundary

that arrives sooner leaves that half still holding the epoch

before last, and the picture comes back a checkerboard of two

scenes. The guard above spaces scene cuts from each other but says

nothing about the boundaries subdivision adds between them, so the

final list is what has to be thinned.

#### `epoch_samples`

Split the palette sample into one bucket per epoch.

The sample is every `sample_stride`-th frame in order, so a movie
frame maps onto a sample row by dividing by that stride. Buckets are
thinned individually, since thinning the whole sample first would
shuffle away the ordering the split depends on.


### [`neogeomedia/fixtiles.py`](neogeomedia/fixtiles.py)

Glyphs for the fix-layer transport overlay.

The fix layer draws 8x8 tiles from the S-ROM over the sprite layer, so
the overlay costs no sprites and never disturbs the video grid. A tile
is 32 bytes of 4bpp pixels, two per byte with the low nibble on the
left, and the four column pairs are stored in the order 0x10, 0x18,
0x00, 0x08. The layout is the one geolith's `geo_lspc_fixline_default`
reads.

Glyphs are drawn as text art rather than loaded from a font file, which
keeps the cart free of any font licensing question and keeps the shapes
editable in place. Index 0 of a fix palette is transparent, so the
overlay paints its own opaque panel behind the text instead of relying
on whatever video happens to be underneath.

The art lives in the core's `fmvcore/glyphs.json`, read through
`fmvcore.font`, one string per pixel row, rather than in the module. Both
players draw text from it. It is data that nothing
computes, so keeping it out of the source keeps the module to the code
that packs it. JSON strings keep the spaces that mark transparent pixels,
which a plain text file would lose to any editor that trims trailing
whitespace.

#### `pack_tile`

Pack one 8x8 nibble tile into its 32 S-ROM bytes.

#### `build_rom`

Pack every glyph into an S-ROM image.

#### `palette_words`

CRAM words for the overlay palette, transparent slot first.


### [`neogeomedia/frames.py`](neogeomedia/frames.py)

Decode a source clip into vblank-rate 320x224 RGB frames.

The Neo Geo raster is 384 pixels by 264 lines at a 6 MHz dot clock, so
the refresh is 6000000 / (384 * 264), about 59.1856 Hz. The player
advances one movie frame per vblank, so the baker resamples the source
to exactly that rate. A 24 fps source therefore repeats most frames,
and a repeated frame costs nothing downstream because every tile slot
is unchanged.

#### `Denoise`

hqdn3d strengths, spatial then temporal.

Denoising runs after the downscale rather than before it, because
what matters here is the temporal stability of the 320x224 tiles the
encoder deduplicates. Grain that survives into the scaled frame makes
every tile differ from its neighbour in time, which destroys the
delta path and inflates the dictionary. Cleaning the scaled image
targets exactly that.

#### `frame_count`

Number of vblank-rate frames covering a duration.

#### `hold_for_target_fps`

Refreshes to hold each frame to land nearest a wanted rate.

#### `source_frames_kept`

Fraction of the source's own frames a hold preserves.

A hold counts display refreshes, not source frames, and the two
differ: a 24 fps source reaching a 59.185 Hz raster already repeats
each frame about 2.47 times. Holding fewer refreshes than that skips
nothing and only shifts which refresh carries the update, so it
costs temporal accuracy and saves no tiles at all.

Interlacing and baked-in bars are detected by `fmvcore.source.analyse`,
which both players share. Interlaced fields woven into a progressive frame
become permanent comb artifacts once they are quantised into character ROM,
and black bars spend the raster on nothing, so both are checked before the
frames are decoded.

#### `_analysed_size`

The frame size after black bars are removed.

#### `plan_geometry`

Work out the crop and scale that fill the raster with a source.

The picture always fills the screen and a wide film loses its sides.
There is no letterbox mode: bars cost tiles like any other picture.

The raster is not square. An AES drives a 4:3 television with 320 by
224 pixels, so a pixel is 0.9333 as wide as it is tall, and a crop
aimed at the raster's own ratio arrives on screen squashed by that
much. Aspect decisions are therefore made in display space and only
converted to pixels at the end.

#### `build_filter`

Build the ffmpeg filter chain for a planned geometry.

Scaling runs before the frame-rate resample so upsampling to the
vblank rate duplicates already-scaled frames instead of scaling the
same source frame two or three times.

#### `decode`

Decode a clip window into vblank-rate RGB frames.

#### `stream`

Yield decoded frames in chunks instead of all at once.

The reference film fills 81% of the 128 MiB character ROM with 35,274
frames, over ten minutes at 59.2 fps. Holding those as RGB would be
over seven gigabytes before the encoder has
allocated anything, so a full-capacity bake is only possible if the
frames arrive a chunk at a time.

#### `sample`

Every `stride`-th frame, for fitting the palette set.


### [`neogeomedia/integrate.py`](neogeomedia/integrate.py)

Apply the edits the bundle's integration guide asks a developer for.

This is the guide in executable form. Every change lands in the
project's own `Makefile` and `rom.mk`, the two files an ngdevkit project
exists to have edited. Nothing here touches a linkscript, and nothing
touches a file the baker emitted. If that ever stops being true, the
shape of the bundle is wrong rather than the shape of this module.

#### `cartridge_edits`

Declare the second program ROM and widen the sprite ROM.

A stock template leaves the second program ROM commented out and
sizes the sprite ROM for a demo logo. A movie needs both, and the
size comes from the fragment rather than from anyone measuring a
file, so a re-bake carries its own new size with it.

#### `makefile_edits`

Include the fragment and point the cartridge at the movie.

The include sits between the cartridge declaration and the build
rules, because the fragment adds its own directories to `SRCDIRS`
and the build rules read that.

The lines that name the template's demo assets are replaced rather
than added to. A cartridge target takes its content from its first
prerequisite, so leaving the stock line in place would build the
ROM from the logo the template ships instead of from the movie.

#### `apply`

Rewrite a stock project's two editable files in place.


### [`neogeomedia/ladder.py`](neogeomedia/ladder.py)

Measure what each quality setting costs, and build the ladder from that.

The rungs used to be hand-picked, with their relative costs written down
from ad-hoc runs. That is how the ladder ended up with a rung strictly
worse than the one below it: nothing was comparing them.

Here a grid of settings is encoded against the same decoded clip, so cost
and error are measured under identical conditions. Anything beaten on both
axes at once is dropped, and the rungs are spread evenly through the cost
that survives. A rung therefore always buys something over the rung below.

Decoding dominates the run, so the clip is decoded once and every setting
is encoded against it.

The ladder's own default, read off a throwaway rung rather than repeated.

A slots dataclass exposes a descriptor rather than the default on the class,
so the value has to come from an instance.

#### `Point`

One measured setting: what it cost and how wrong it looked.

#### `measure_point`

Encode one setting against an already decoded clip.

#### `frontier`

Drop every setting beaten on cost and on error at once.

What remains is the set worth having a rung for: each one is either
cheaper or better than everything else that survived.

#### `choose`

Spread `count` rungs evenly through the measured cost range.

Even spacing in cost, not in list position, is what makes a rung buy
something: a frontier can crowd twenty settings into a few percent and
leave a chasm below them.

#### `to_tiers`

Turn measured points into ladder rungs with costs relative to the reference.

The top rung searches every palette rather than a shortlist. It is the
rung chosen when nothing is being economised, so the one place where the
shortlist's occasional wrong pick is not worth its speed.

#### `sweep`

Measure every setting in the grid against one source.

#### `_paired_tolerances`

Loosen the redraw threshold in step with the colour weight.

The two levers move together: a picture already charged less for colour
error has nothing to gain from being redrawn on a colour change too
small to see.


### [`neogeomedia/mamecart.py`](neogeomedia/mamecart.py)

Package the cart for MAME as well as for a flash cart.

Everything this project encodes was confirmed against geolith, which
models the board rather than being it. MAME is a second, independent
implementation, so a cart that behaves identically in both is far more
likely to be right on a console than one confirmed by either alone. That
matters here because the two emulators do not agree on everything: MAME
masks the program-ROM bank register with 0x07, matching the three-bit
latch on real hardware, while geolith allows far more banks. A cart that
overruns eight banks runs in geolith and reads the wrong bank on
hardware.

The dataarea names, sizes and load flags are the ones MAME's Neo Geo
cart slot looks for in `src/devices/bus/neogeo/slot.cpp`. `maincpu`
loads word-swapped because the ROM image is in physical MASK ROM order,
and the two character halves load byte-interleaved.

#### `_rom_element`

Add one rom entry.

The offset is not optional. MAME's own software lists carry it on
every entry, and an interleaved pair needs 0 and 1 to land on
alternating bytes. Omitting it loads both halves at zero, so the
second silently overwrites the first and the sprite layer decodes
from wrong data.

#### `build_software_list`

Build the software-list entry MAME binds cart regions with.

#### `write_cart`

Write the MAME zip and the software list that binds it.


### [`neogeomedia/neocolor.py`](neogeomedia/neocolor.py)

Neo Geo palette color model and perceptual distance.

The palette word layout and the digital-to-analog mapping are taken from
the geolith LSPC implementation, `src/geo_lspc.c`, `geo_lspc_palconv` and
`geo_lspc_palgen_raw`, because geolith is the decoder this project
verifies against. The word is

    |D0|R1|G1|B1|R5 R4 R3 R2|G5 G4 G3 G2|B5 B4 B3 B2|

Each channel carries five independent bits plus `D0`, a sixth bit shared
across all three channels. geolith reconstructs a six-bit level per
channel as `(c5 << 1) | D0`, inverts `D0`, and scales to eight bits with
the integer form of `value * 255 / 63 + 0.5`.

`D0` is fixed to zero by the baker. It buys half a level per channel,
roughly 1.6 percent, which is far below the error the fifteen-colors-per
-tile constraint already imposes, and fixing it keeps one color grid
across every pass.

Two digital-to-analog models exist. `geo_lspc_palgen_raw` treats the
level as a plain fraction of full scale. `geo_lspc_palgen_resnet` models
the actual resistor ladder on the board, five resistors per channel at
3900, 2200, 1000, 470, and 220 ohms, smooths the resulting curve, and
renormalizes. The resistor model is the default here because it is what
real hardware does, and because it is the emulator setting this project
captures against. It also reaches true black at level zero, where the
raw model bottoms out at 4.

The Oklab matrices are Bjorn Ottosson's reference coefficients, matching
`rgb_to_oklab` in the DoomNG `tools/doomng_build/bake/palette.py`,
vectorized over numpy arrays here.

#### `pack_palette_word`

Encode one CRAM word from 5-bit channels.

#### `rgb_to_color_index`

Map 8-bit sRGB triples to the 15-bit Neo Geo color grid index.

#### `color_index_to_c5`

Split a color-grid index back into its three 5-bit channels.

#### `color_index_to_rgb`

Displayed sRGB for each color-grid index.

#### `color_index_to_palette_word`

Encode CRAM words for a batch of color-grid indices.

#### `build_oklab_grid`

Oklab coordinates of every color on the 15-bit Neo Geo grid.


### [`neogeomedia/neofile.py`](neogeomedia/neofile.py)

Write the .neo cart container without loading the cart into memory.

This replaces neosdconv, which holds the whole cartridge in a Node heap
and is killed by the OOM reaper once the C-ROM passes a few tens of
megabytes. A movie cart is mostly C-ROM by definition, so that ceiling
bounded the entire project. Writing the container in fixed-size chunks
keeps memory flat no matter how long the movie is.

The layout was recovered from a known-good neosdconv file and
cross-checked against geolith's `geo_neo_load`. A 4096-byte header holds
a magic tag, six little-endian region sizes, four metadata words, a
33-byte name and a 17-byte manufacturer. The regions follow in the order
P, S, M, V1, V2, C. A `v21.v2` file is optional: when present it becomes
the ADPCM-B region, and when absent the loader points ADPCM-B at the
ADPCM-A data instead. The character region is the two ROM halves
interleaved byte by byte, which is what the LSPC tile decoder expects.

This module imports only the standard library so the build can run it
with whatever bare python3 the toolchain container happens to ship.

#### `build_header`

Build the 4096-byte container header.

#### `write_neo`

Assemble the cart regions into a .neo container.


### [`neogeomedia/palettes.py`](neogeomedia/palettes.py)

Per-tile palette clustering and assignment.

The LSPC gives each 16x16 tile one CRAM bank of 16 entries, and entry 0
is transparent, so a tile is quantized to 15 colors chosen from a bank.
With 256 banks and 16 reserved for the fix layer, the video draws from
240 banks, or 3600 simultaneous colors, and the encoder's job is to pick
banks that let every tile in the movie land close to its source colors.

The approach follows the tiled-palette-quantizer family: describe each
tile compactly, cluster tiles into as many
groups as there are banks, fit a palette per group, then assign every
tile to whichever bank quantizes it best. Clustering uses a nine
dimensional descriptor, the Oklab mean plus the darkest and brightest
pixel, because tiles that agree on those three points almost always
share a palette well.

Palette entries are chosen from colors that actually occur in the
source rather than from arbitrary grid points, the same choice
`median_cut_select` makes in the DoomNG `palette.py`, so a palette never
spends a slot on a color the content does not contain.

Distance is squared Oklab throughout, matching `oklab_distance_sq` in
the DoomNG `palette.py`.

Optional ordered dithering trades a little spatial noise for smoother
gradients. Error diffusion is unavailable here for a structural reason:
it makes a tile's output depend on its neighbours, so two identical
source tiles stop quantising alike and stop interning as one, which
spends the C-ROM this design is short of. A Bayer threshold has neither
problem. It depends only on where a pixel sits inside its own tile, and
because the matrix is 8x8 and a tile is 16x16 it also runs continuously
across tile boundaries, so identical tiles still collapse to one entry.

The threshold field and the pattern dither live in the core,
`fmvcore.dither`. `bayer_thresholds(TILE_PX)` tiles the 8x8 matrix over a
16x16 tile, so every tile sees the same field and identical tiles still
quantise identically. `pattern_candidates` takes four picks for a colour,
each the nearest entry to the colour plus the error the earlier picks
left, darkest first, and `pattern_pick` lets the threshold choose one by
rank. The picks depend only on the colour and the bank, so
`PaletteAssigner` builds them once per bank for all 32,768 colours, and a
tile still quantises the same wherever it sits.

Four picks can mix three or four entries of a bank, where the two-entry
mix the Master System keeps can mix only a pair. On the six regression
films at `q17` the two-entry mix tied with no dither, -1.9% to +0.5%;
four picks beat no dither on all six, 0.2% to 6.0% lower blurred error,
for about 1.2% more C-ROM tiles. One rung finer, `q16`, costs 4.2% more
tiles for 5.0% lower error, so the picks buy about twice as much picture
per tile as a rung does. Adding the error up in linear light measured
0.2% worse, and sixteen picks gained more but baked six to ten times
slower. A dithered bake takes two to three times as long. The default
stays off, waiting on the owner's dither verdict.

#### `oklab_grid`

Color index to Oklab, with the chroma axes optionally scaled down.

Vision resolves luminance far more finely than colour, which is why
every broadcast and consumer codec since the 1950s has spent fewer
bits on chroma than on luma. Angel Studios leaned on exactly this to
fit Resident Evil 2's video into 24 MiB, quartering the horizontal
chroma resolution outright.

There is no separate chroma plane to subsample here, because a tile
is a palette index and not a Y/Cb/Cr triple. The equivalent lever is
the distance metric every stage already shares: scaling the `a` and
`b` axes by the square root of the weight makes a squared distance
charge chroma error at `chroma_weight` times the rate of luma error.
Palette fitting, palette assignment, redraw decisions, and motion
masking all measure distance through this table, so weighting it
here moves the whole encoder onto a luma-first metric at once.

A weight of one reproduces unweighted Oklab.

#### `bank_of`

CRAM bank holding a palette.

#### `cram_blob`

CRAM words for every palette, transparent slot first.

#### `rendered`

Color indices the hardware will actually display.

#### `_sqdist`

Pairwise squared distance without materializing the difference tensor.

The expanded form keeps memory at one value per pair instead of one
per pair per dimension, which matters because a feature-length bake
ranks hundreds of thousands of tiles against 240 palettes.

#### `build_palette_set`

Cluster a sample of tiles and fit one palette per cluster.

Each bank's fit runs weighted k-means from the heaviest colours, then
migrates its weakest centroid: the one whose colours lose least if it goes
moves to the farthest colour of the cluster with the most error, up to ten
rounds, and a round is kept only when the total error falls. It is the
utility migration of enhanced LBG, and it lowered blurred error on all six
regression films, 1.3% to 5.4%, with C-ROM tiles equal or fewer and about
a quarter more bake time. Re-fitting the banks around each tile's true
quantisation error instead of its descriptor was measured and dropped:
the films moved -0.2% to +0.7% for twice the bake time, so the descriptor
fit already sits near the plateau at 240 banks. Sorting each bank's
entries by lightness, so equal index patterns under different banks share
a C-ROM tile, changed no tile count: a flat tile reduces to one of fifteen
patterns whatever the order, and textured tiles never repeat exactly
across banks.

#### `PaletteAssigner`

Picks the best palette for each tile and emits its pixel indices.

#### `assign`

Choose a palette per tile and quantize its pixels.

#### `_quantise`

Pixel indices for a chunk of tiles, dithered when asked for.

The dither is a strength from 0 to 1, as on the Master System player.
It scales how much of the earlier picks' error each pattern pick carries,
so 1 is the full pattern and 0 is the nearest entry everywhere. The
default stays at 0 until the dither is judged by eye on the board.


### [`neogeomedia/plan.py`](neogeomedia/plan.py)

Report what a source can become on a cartridge, without baking it.

Calibrating takes well under a minute while a full bake takes hours, so
this exists to answer the question that decides the bake: what quality
is reachable, and what would trimming the source buy. Everything it
learns is printed rather than acted on, because shortening a film is the
owner's decision and not the baker's.


### [`neogeomedia/preview.py`](neogeomedia/preview.py)

Write a viewable copy of what the cartridge will show.

The preview output re-encodes the decoded picture at the vblank rate, so
the quantization can be judged in motion without booting a cart.

#### `preview_codec`

Lossless for .mkv, viewable h264 otherwise.

A lossy preview layers its own artifacts on top of the quantizer's,
which is exactly what a quality judgement must not do, so the
verification path writes FFV1 and only the shareable copy is h264.

#### `PreviewWriter`

Feeds rendered frames to ffmpeg as they are produced.

#### `StillWriter`

A `.png` preview: four frames spread across the film, each console frame
beside the source frame it was made from, the same comparison the Master
System player writes. Only the four picked frames are kept in memory.

A full-capacity bake renders more frames than fit in memory, so the
preview cannot be assembled at the end. Frames go down the pipe as
the encoder finishes them.


### [`neogeomedia/probe.py`](neogeomedia/probe.py)

Find the tier a source supports by baking, never by predicting.

Calibration samples short windows and extrapolates, and it reads high by
construction: every window starts with a cold dictionary where almost
every slot mints a tile, while a full bake amortises reuse across the
whole film. On the reference film it predicted 946,352 tiles where the
encoder spent 846,784. Worse, the ratio between two rungs is a property
of the content rather than of the settings, so no table can price them
for every film.

So nothing is predicted here. Rungs are baked and the results are read.
What is measured is measured, and what is not measured is not guessed
at.

Which rungs get baked is a separate question from whether anything is
estimated. Cost falls strictly from every rung to the next, and a rung
that fits implies every cheaper rung fits, so the rungs that fit form a
suffix of the ladder and only its boundary has to be found.

The search still starts at the richest rung, because a source that can
afford it should cost one bake to discover. When that rung does not fit
the probe doubles its stride, `q02`, `q04`, `q08`, until a rung fits,
then bisects the bracket that doubling just proved. The answer is the
same rung a walk from the top would reach; what changes is that a film
settling deep in the ladder costs about nine bakes instead of thirty.

A rung fails in three ways, and all three mean the same thing. It can
fill the dictionary, it can pass the tile budget, or it can stay inside
the budget only because rate control degraded it far enough to get
there. The third is the one worth naming: the controller trades picture
quality for room, so a rung rescued at its ceiling is nominally richer
than the rung below while looking worse. Accepting it would defeat the
search.

#### `Reading`

What one bake spent, and whether it finished on its own terms.

#### `fits`

Whether this rung finished the film inside the cartridge.

#### `Outcome`

The rung the source supports, and what was learned getting there.

#### `candidates`

The ladder, richest first, without rungs the baker would refuse.

#### `search`

The richest rung that fits, settled by baking.

Never shortens the source. A source that fits nowhere comes back with
no tier, leaving the decision to trim where it belongs.

The bracket and the binary search are `fmvcore.ladder.first_fit`, which the
Master System player's step-down shares.

#### `_fits`

Whether this rung fits, baking it only if nothing already knows.


### [`neogeomedia/quality.py`](neogeomedia/quality.py)

Quality tiers, and choosing one that fits the cartridge.

A cartridge holds a fixed number of tiles, so the longest movie it can
play is decided by how many tiles each minute costs. That cost is a
property of the content rather than of the running time: dense animation
can cost several times what a dialogue scene costs. A ladder indexed by
duration alone would therefore over-compress easy sources and
under-compress hard ones, so the rate is measured on the source itself
and the ladder only says how to spend what was measured.

Three ceilings bound a bake. Character ROM holds the tile dictionary and
binds first at every tier measured. Program ROM carries the command
stream and keeps around half its space spare throughout. The ADPCM-B
voice ROM holds the soundtrack and only constrains anything past about
ten minutes, where the sample rate has to come down to fit.

The relative costs below were measured on dense animation. They set the
shape of the ladder, never its absolute position, which calibration
supplies per source.

The rungs follow the measured Pareto frontier, which turned out to hold
a surprise: frame rate is a far worse thing to spend than colour. At a
fixed cost, keeping every frame and thinning the palette beat dropping
to a third of the frame rate by nearly half the error, and did it for
fewer tiles. Every rung down to 0.645 therefore keeps all 59.2 frames a
second, and holding frames only begins once colour has been spent all
the way down. An earlier ladder started dropping frames at 0.686, above
the point where the data says not to, which is why its middle rungs felt
like a cliff rather than a step.

Steps are around 9%. Finer would be false precision: the costs come from
one clip, so a 5% difference between neighbours sits inside the noise of
the measurement that produced them.

There is no lossless rung and there cannot be one. A tile draws from a
single bank of 15 colours, and 83% of tiles in real footage hold more
distinct colours than that once the picture is reduced to the hardware's
15-bit palette, so the quantisation step always discards something. The
top rung instead guarantees that nothing the encoder controls is given
up: every frame is shown, no drift is tolerated, colour is charged at
the same rate as luminance, nothing is denoised, and every palette is
searched rather than a shortlist.

Where the source's own cost curve is measured.

One anchor is not enough. Measured across four sources, the cost of a
setting relative to the reference agreed by construction at the reference
and diverged by up to 2x at the extremes: at colour 8% the cheapest source
came in at 0.378 and the dearest at 0.756. A ladder averaged over sources
therefore mispredicts any single one, and it does so worst exactly where
the rungs are cheapest. Three anchors pin both ends and the middle.

The fourth sits on a frame-hold rung. Measured across the whole ladder on
one source, the three chroma anchors left the hold rungs to extrapolation
and the error ran the unsafe way: q32 through q35 cost 9%, 13%, 22% and
26% more than predicted, so the planner promised runtime the cartridge
could not hold. Every chroma rung was conservative by 2% to 9% over the
same measurement. Anchoring inside the hold range replaces that
extrapolation with a reading.

#### `Tier`

One rung of the ladder, and what it costs relative to `standard`.

#### `tier_by_name`

Look a tier up by name, listing the ladder when it is not one.

The older seven names still resolve, to the rung nearest what they
used to mean, so existing commands keep working.

#### `effective_fps`

Frames per second this tier actually shows.

#### `tile_rate_for`

Tiles per minute this tier costs, given the measured reference.

The ladder's cost is averaged over several sources, and the shape of
that curve is a property of the content: measured across four sources
the same setting varied by up to 2x at the extremes. When the source's
own anchors are known, the averaged cost is bent onto them.

#### `max_minutes`

Longest movie this tier fits, before any safety margin.

#### `audio_grade`

Where a sample rate sits on the same scale the picture uses.

The rate itself is never rounded to a step. Audio lives in its own
ROM and competes with nothing, so the planner always takes the
highest rate that fits and stepping it could only give quality away.
This is for reporting: it places whatever rate came out on the same
eighteen-rung scale as the picture, so the two are comparable at a
glance. Grade one is the chip's own maximum, and each grade down is
the same ratio the picture ladder uses between neighbours.

#### `audio_hz_for`

Highest sample rate whose soundtrack the player can still address.

Audio lives in its own ROM, so a finer rate costs the picture
nothing at all and the only thing holding it down is how long the
movie runs. It therefore starts at what the chip itself can play and
comes down only far enough to fit.

The limit is the page counter rather than the ROM. ADPCM-B addresses
in 256-byte pages through a 16-bit register, so the last page a
player can name is 65,535 and filling the voice ROM to exactly its
16 MiB puts the final page one beyond that. The counter wraps and
playback restarts from the beginning of the sample.

The rate is then floored onto the chip's own Delta-N grid, because
the encoder quantises to that grid afterwards and rounding to the
nearest step can come back a fraction above what was asked for. A
fixed safety margin cannot cover that, since the excess grows with
runtime; landing on the grid deliberately does.

#### `Fit`

How one tier stands against a specific runtime.

#### `overshoot`

How many times over capacity the source runs, 1.0 when exact.

#### `spare_minutes`

Runtime still available at this tier, negative when over.

#### `trim_minutes`

Runtime that would have to come out to reach this tier.

Rounded up to the next whole second. The exact shortfall lands on
the boundary, where floating point can leave a source a
fraction over after trimming by precisely the figure it was
given, and advice that does not quite work is worse than none.
Seconds are also the unit the figure is displayed in.

#### `clock`

Runtime as h:mm:ss, or m:ss when under an hour.

#### `_estimate_caveat`

Say plainly how far this choice can be wrong, and what is not a guess.

The rungs are priced by one ladder of relative costs, and measurement
says no single ladder can be right: how much a colour reduction saves
depends on the content. On the animated reference film q17 really
costs 0.43 of q01 where the ladder says 0.65, so the plan promises
less runtime than the cartridge has. On a grainy live-action clip the
same rung costs 0.75, so the plan promises more.

#### `format_plan`

A full account of what this source can become, and what it costs.

Written to be acted on rather than skimmed. Every tier is listed with
the runtime it holds for this particular source, so a runtime that
just misses a better tier shows exactly how much has to come out, and
trimming the source stays a decision the person makes with the
numbers in front of them.

#### `reachable`

Whether baking this tier would drop any of the source's own frames.

A hold counts display refreshes rather than source frames. A 24 fps
source reaching a 59.185 Hz raster already repeats each frame about
2.47 times, so holding two refreshes still shows every frame it had:
the tier costs temporal accuracy and saves not one tile. The baker
refuses such a hold, so offering it hands back a tier that cannot be
baked.

#### `survey`

Every tier measured against one runtime, best quality first.

Given the source's frame rate, tiers the baker would refuse are left
out rather than offered and then rejected.

#### `shortfall_message`

Why a source cannot be baked at all, or None when some tier fits.

Kept apart from the command line so the decision, and the number the
reader is asked to act on, can be checked without a source long
enough to actually overrun a cartridge.

#### `select`

The best tier that fits, or None when even the cheapest overruns.

#### `anchor_tiers`

The rungs worth measuring on this source.

A hold anchor is only meaningful when the hold actually drops source
frames. On a slow source it would measure the same cost as no hold at
all and pin the curve to a value that says nothing.

#### `rescale`

Bend the ladder's averaged cost onto the curve this source actually has.

The anchors map a rung's averaged relative cost to what the source
measured there. Rungs between two anchors are interpolated in log space,
which keeps the ordering: a rung cheaper on the ladder stays cheaper
after correction.

#### `nearest_by_chroma`

The rung whose colour weight is closest to a wanted one.


### [`neogeomedia/ratecontrol.py`](neogeomedia/ratecontrol.py)

Pace tile spending against the cartridge's budget.

#### `RateController`

Keeps tile spending on pace so the movie fits the cartridge.

A tier is chosen from a sample, and a sample cannot know that the
third act is busier than the first. Left alone the dictionary runs
out partway through and every remaining slot freezes, which wrecks
the end of the film instead of costing a little quality across all
of it.

Correcting from cumulative overshoot proved far too slow. By the
time the running total is visibly over, the only thresholds that
would still recover the deficit are ones this controller would take
hundreds of frames to reach, so it arrives after the dictionary has
already hit its cap. This instead compares the recent rate of tile
creation against the rate the remaining budget affords, and holds a
multiplier that persists between frames so it keeps moving until it
actually bites.

The multiplier never falls below one, so the tier's threshold is a
floor and the controller only ever tightens. Letting it relax was
tried, in the hope of spending the capacity a discrete tier leaves
behind, and it loses in both the forms attempted. Tile spending is
heavily front-loaded, since an empty dictionary mints a tile for
almost every slot and a full one reuses: over one clip the four
quarters spent 7,030, 16,229, 11,572 and 22,704 updates against a
flat expectation of 14,247. A controller pacing against a uniform
budget therefore relaxes exactly when spending is naturally light
and starves the passages that legitimately need the tiles. Filling
the cartridge to 100% that way scored 26.63 where never relaxing
scored 20.11.

Spending the leftover capacity needs a budget curve shaped like the
content rather than a straight line, which is a two-pass problem.

The multiplier never falls below one, so the tier's own threshold is
a floor and the controller can only tighten.

#### `tolerance`

The error budget for this frame.


### [`neogeomedia/redraw.py`](neogeomedia/redraw.py)

Decide which slots a frame redraws and when a frame is a cut.

#### `masked_threshold`

Per-slot error budget, raised where the picture is moving.

Vision is far less sensitive to spatial detail in a region that is
changing quickly, and far more sensitive in one that is still, where
an error sits on screen and stays visible. A single flat threshold
spends the same precision on both. Scaling the budget by how much
the source itself moved buys back tiles from exactly the places the
eye cannot inspect them, which is the whole point of a lossy codec.

A masking factor of zero reproduces the flat threshold.

Masking is only safe because a skipped slot stays pending and is
re-tested every frame. Once its motion stops the budget collapses
back to the flat threshold and the slot is corrected, so an error
hidden by movement never outlives the movement that hid it.

#### `movement`

Mean squared Oklab distance the source itself moved, per slot.

#### `is_scene_cut`

Whether the picture jumped rather than moved.

A cut earns a keyframe because a delta could not be cheaper when
nearly every slot has to be rewritten anyway. Deciding that on the
count of slots that differ at all does not work on photographed
material: grain, dither, and any gentle camera move perturb almost
every slot by a shade every frame, so a plain count reads a still
scene as a cut. Measured on real footage that fired on 22% of all
frames, and each false cut rewrote all 280 slots and interned the
tiles a delta would have skipped.

Magnitude separates the two cases cleanly. A slot counts toward a
cut only once the source moved further than `scene_cut_floor`, which
leaves gradual motion to the delta path where it belongs.

#### `select_targets`

Which slots to redraw this frame, and which stay owed a redraw.

A keyframe takes every slot and clears the backlog, which is what
makes it a seek target. Otherwise a slot is a candidate when its
source changed or when an earlier frame skipped it, and it is only
redrawn when the picture on screen has drifted past the budget.

A skipped slot stays pending rather than being forgotten, so an
error the encoder chose to tolerate is re-tested on every later
frame and repaired as soon as it stops being cheap to hide.


### [`neogeomedia/screen.py`](neogeomedia/screen.py)

Model the picture the LSPC is showing, slot by slot.

#### `Screen`

What the LSPC is currently showing, tracked slot by slot.

#### `drift`

Mean squared Oklab distance between the source and the picture on screen.

#### `retarget`

Point the model at a new epoch's colours.

What is on screen does not change, so the model of it must not
either. Only the palettes that later assignments are measured
against move.

#### `fidelity`

Mean squared Oklab error of the whole displayed frame.

Deliberately measured on the unweighted grid over every slot,
including the ones the encoder chose not to redraw. `mean_error`
averages the palette error of tiles that were written, so it
improves when the encoder skips more work, which makes it
useless for judging output quality. This is the number that
answers whether the picture on screen still matches the source,
and no encoder knob can flatter it.

The comparison is against the true source frame for this refresh,
never the frame the encoder chose to hold. Holding a frame across
four refreshes is a real error the viewer sees, so measuring
against the held copy would score a cheat as free.

#### `commit`

Write the chosen tiles into the model and list what must be sent.


### [`neogeomedia/soundtrack.py`](neogeomedia/soundtrack.py)

Turn the source soundtrack into the voice ROM and its register values.

Whether the source has a soundtrack at all comes from `fmvcore.ffmpeg.has_audio`.

The decoded samples pass through `fmvcore.condition` before ADPCM-B encoding, so
a quiet source can be lifted to use the predictor's range and a loud one tamed
before it clips. Every stage is off by default, so an unconditioned bake is
byte-identical to one before the stage existed; a stage is turned on only once
it has been measured against this console's output and heard on a board, which
is the family's rule for an audio change. The `measure_audio.py` script is the
yardstick that measurement reads.

#### `decode_audio`

Decode the source soundtrack to mono 16-bit at the target rate.

A source with no audio track is a normal input, not a failure, so
this reports an empty signal and the bake simply omits the voice ROM.

#### `audio_pages_per_frame`

Voice-ROM pages advanced per video frame, as an exact fraction.

The player multiplies a frame number by this to find where in the
soundtrack that frame sits, which is what lets a seek re-point audio
and video together. Two samples share a byte and a page is 256
bytes, hence the 512.

This is deliberately a ratio rather than fixed point. A rounded
fixed-point step accumulates: at 4096ths of a page the error reaches
a quarter of a second by the half-hour mark, which is a visible lip
sync failure. An exact ratio keeps the error at the page
quantization alone, about 23 ms, no matter how long the movie runs.

#### `write_audio_params`

Emit the ADPCM-B register values the Z80 driver assembles against.


### [`neogeomedia/stamp.py`](neogeomedia/stamp.py)

Keep the library header's version in step with the package's.

A release bumps `FMV_VERSION` in `src/fmv/fmv.h`, because that is the
one form python-semantic-release can rewrite in a C header. The numeric
major and minor beside it are what the generated movie header compares
against at compile time, and the preprocessor cannot split a string, so
they are rewritten from it here.

The release runs this as its build command. Anyone can run it by hand;
running it when nothing has moved rewrites nothing.

#### `restamp`

Rewrite the numeric defines from the version string above them.


### [`neogeomedia/stream.py`](neogeomedia/stream.py)

Keyframe and delta command stream for the on-cart player.

The screen is a 20 by 14 grid of 16x16 tiles held by sprites 1 to 20,
one sprite per column, chained with the SCB3 sticky bit. Sprite index 0
is never drawn by the LSPC, so the grid starts at sprite 1. A slot's
SCB1 entry therefore sits at word address `(col + 1) * 64 + row * 2`.

A frame record is a list of runs. A run carries a VRAM word address and
a count, followed by that many tile-number and attribute word pairs. The
player writes the address to REG_VRAMADDR once, sets the auto-increment
modulo to 1, and streams the words straight out of ROM, so a run costs
one register setup regardless of length. Consecutive rows in the same
column merge into one run, which makes a full keyframe exactly twenty
runs.

Every field is a big-endian 16-bit word, matching 68000 byte order, so
the player never byte-swaps.

#### `vram_address`

SCB1 word address of a grid slot's tile entry.

#### `attribute_word`

Build the SCB1 odd word for a tile entry.

#### `pack_frame`

Pack one frame's slot updates into a run-coded record.

#### `MovieStream`

Accumulates frame records and the seek index that points at them.

The stream lives in the 68000's switchable P-ROM window, so a frame
record must never straddle a bank boundary; the player would have to
change banks mid-record to finish reading it. Padding a record
forward to the next bank costs at most one record per megabyte and
keeps the player's inner loop free of any bank check.

#### `append`

Add one frame record, keeping it inside a single bank.

#### `payload_size`

Bytes written so far, before padding out to whole banks.

#### `bank_count`

Number of switchable banks the stream occupies, always at least one.

Real hardware latches only three bits of bank number, and MAME
masks the register with 0x07 to match. geolith allows far more,
so a cart that overruns eight banks runs correctly in one
emulator and silently reads the wrong bank on a console. The
limit is enforced at bake time rather than discovered on
hardware.

#### `blob`

The stream padded out to whole banks.


### [`neogeomedia/subtitles.py`](neogeomedia/subtitles.py)

Turn a subtitle sidecar into a table the player can read in vblank.

The player has no string handling and no time to do any: it gets one binary
search per frame and a row of glyph indices to copy. Everything that can be
decided ahead of time is decided here.

Records are fixed width so the search is an index rather than a walk, and
the text is already laid out, centred, and translated into fix-layer tile
numbers. The 68000 copies bytes into VRAM and does nothing else.

Cues are trimmed so that no two overlap, because the fix layer shows one
thing at a time and a player that had to merge them would need the string
handling this format exists to avoid.

#### `layout`

Wrap to the raster without splitting words, keeping the lines that fit.

A single word too long for a row is cut instead of dropped: losing the
line entirely is worse than losing its tail.

#### `frame_span`

The half-open frame range a cue is on screen for.

#### `encode`

Pack cues into fixed width records of frames plus laid-out glyph rows.


### [`neogeomedia/tiercache.py`](neogeomedia/tiercache.py)

Remember what a source actually cost, so it is measured once and never guessed.

Calibration samples short windows and extrapolates, and it is biased by
construction: every window starts with a cold dictionary where almost
every slot mints a tile, while a full bake amortises reuse across the
whole film. Measured against a real bake it read 946,352 tiles where the
encoder spent 846,784.

A bake is about eight minutes for a ten minute source, only four times
what calibration costs, so measuring the real thing is affordable. What
makes it worth doing once is this: the reading is stored against the
source's own bytes, and every later run reads it back instead of
sampling anything.

A reading is stored against the window it measured, start and duration
included in the key, because a rate taken over ten minutes says nothing
certain about sixty: a film's second hour is not as busy as its first.
Widening the window asks a new question and gets a fresh bake.

What is stored per rung is a rate rather than a verdict, so the same
reading answers both "does this fit" and "by how much".

The file lives at the top of the project rather than in a user cache,
because what it holds is a property of the film and the ladder rather
than of one workstation. Committing it lets everyone building the same
cartridge skip the same bakes. It is written sorted and one field per
line so a diff reads, and each entry carries the file name and the
window beside the readings, since a key that is only a hash tells a
reviewer nothing.

#### `Params`

Everything outside the tier that changes what a bake costs.

#### `default_store`

The versionable file at the top of the project.

#### `content_digest`

A cheap fingerprint of the bytes rather than of the name.

Hashing a whole feature would cost more than the bake it saves, so
this reads the head and the tail and mixes in the length. A rename
keeps the key, an edit loses it, and two files that differ only deep
in the middle at exactly the same length would collide, which is a
trade the cost of the alternative earns.

#### `_read`

Every entry in the file, or nothing if it is absent or foreign.

#### `recall`

What is settled about this source.

A number is the rate that tier really cost, in tiles per minute. A
null is a rung that was baked and overran, which is worth keeping so
it is never baked again.

#### `remember`

Record one settled rung, leaving the others alone.

#### `describe`

Name the entry, so a reviewer reading the file knows what it is about.

The key is a hash and stays a hash, because the file name is not
stable enough to key on. These fields sit beside it for people.

#### `settled`

Whether this rung has already been baked for this source.

#### `fits`

Whether a settled rung fit. Meaningless for an unsettled one.

#### `best_known_fit`

The best rung already proved to fit, without predicting anything.

Walks from the best rung down and stops at the first that is both
settled and fitting. A rung that has never been baked stops the walk
rather than being guessed at, because an unsettled rung above the
answer is exactly what still needs measuring.


## The scripts

### [`scripts/measure_audio.py`](scripts/measure_audio.py)

Measure a baked voice ROM against the soundtrack it came from, so a choice of
conditioning rests on a number rather than a hope.

It decodes the voice ROM through the chip's own state machine, decodes the same
source window, and reports three things: the output's loudness, the gain the
conditioning applied, and a segmental signal-to-noise ratio of the output
against the source. The SNR level-matches the two first, so a stage that only
changes loudness does not read as a loss by construction, which is the trap the
picture measurements warn about. The loudness and gain show what a stage did;
the SNR shows whether it cost fidelity. A number from here is a shortlist, not a
verdict: the owner still hears it on a board before a stage ships on.

### [`scripts/measure_drift.py`](scripts/measure_drift.py)

Report how far the player's frame counter has fallen behind the raster.

A capture taken after N vblanks should show movie frame N. Any shortfall is
the player missing its deadline: the movie advances one frame per vblank it
survives, and a frame whose work overruns costs a whole extra vblank. The
sound chip does not wait, so the shortfall measured here is the gap the ear
eventually hears.

The stream is replayed once and every candidate in the window is scored
against the same pass, rather than replaying from the start per candidate.

The menu owns the first sixteen palettes, so video starts above them.

Errors this close are the same picture, not a better one.

#### `_both_halves`

Place an epoch's palettes in the CRAM half it occupies.

A scan crosses epoch boundaries, and a slot interned under the previous
epoch still points into the other half. Rendering both halves lets that
slot resolve to black and score badly rather than raise, which is what a
search wants: the wrong candidate should lose, not stop the scan.

#### `measure`

A static shot repeats itself exactly, so the match is a run of

frames rather than one. The player is somewhere in that run, and

the only defensible pick is the end nearest where it should be.


### [`scripts/sweep_ladder.py`](scripts/sweep_ladder.py)

Measure every rung of the quality ladder against one window.

The ladder claims to be a frontier: no rung costs as much as another
while looking no better. Nothing checked that until this existed, and
the claim is worth checking because the planner trusts the declared
costs to decide what fits a cartridge. Baking the same window at every
tier turns the claim into a measurement, and turns the declared costs
into an error bar against what the encoder actually spends.

Each bake gets the whole tile budget for a short window, so the rate
controller never engages and every rung reports its natural cost rather
than what a controller squeezed it into.

#### `Measurement`

What one rung cost on the window every rung saw.

#### `cost_inversions`

Neighbours where the cheaper-looking rung costs more.

#### `error_inversions`

Neighbours where giving up quality improved the picture.

#### `dominated`

Rungs another rung beats on cost and on error at once.

A rung that costs at least as much as another while looking no
better has no reason to exist: anyone who would pick it is better
served by the rung that beats it.

#### `model_error`

How far each rung's declared cost sits from what it actually cost.

Positive means the rung costs more than the ladder claims, which is
the unsafe direction: the planner promises runtime the cartridge
cannot hold.

#### `verdict`

Zero when the ladder is a frontier, non-zero when it is not.


### [`scripts/verify_capture.py`](scripts/verify_capture.py)

Match a geolith screenshot against the baker's own rendered frames.

The boot delay between powering the cart and the first movie frame is not
known ahead of time, so this searches every rendered frame for the one
that best matches the capture instead of assuming an offset. A near-zero
best match proves the whole chain agrees with the emulator: the packed
C-ROM bytes, the SCB attribute words, the palette upload, the run-coded
stream, and the player's VRAM writes.

The capture is cropped by geolith's overscan options, so the reference
frames are cropped the same way before comparison.

Errors this close are the same picture, not a better one.

#### `tied_run`

The frames around the best match that score identically to it.

A 24 fps source shown on a 59.185 Hz raster repeats each frame about
two and a half times, so a match is a run rather than a single
frame. Every member of that run is the same picture, and none of
them is a rival to the others.

#### `stream_preview`

Rendered frames from a preview, one at a time.

A feature-length preview decodes to several gigabytes of raw RGB, so
holding all of it to search for one matching frame exhausts memory
and the process is killed. Reading the pipe a frame at a time keeps
the cost at one frame regardless of how long the movie runs.

#### `decode_capture`

One screenshot at whatever geometry the emulator produced.

#### `downscale_capture`

Undo the front end's integer upscale, if it applied one.

RetroArch writes the screenshot at the window scale rather than at
the emulated resolution, so a capture arrives as a whole multiple of
the active area. Sampling the centre of each block recovers the
original pixels exactly for nearest-neighbour scaling and stays
representative for any other filter.

#### `_epoch_palettes`

The palette set on screen at a frame, and which half it sits in.

Colours are refitted per scene into alternating halves of CRAM, so a
reconstruction has to pick the epoch covering the frame and read its
slice of the blob. A movie with one epoch keeps the whole blob.

#### `reconstruct_frame`

Rebuild one frame's picture from the cart artifacts alone.

Replaying the stream into the VRAM model and rendering from the
packed C-ROM reproduces exactly what the hardware shows, without a
preview video. Long bakes cannot keep every rendered frame in
memory, so this is the only reference available for them.


## The tests

### [`tests/conftest.py`](tests/conftest.py)

#### `never_touch_the_committed_store`

Keep the project's own tier file out of every test's reach.

The store moved from a user cache to a tracked file at the top of
the project, which put it one unstubbed call away from any test that
exercises the search. A test that writes it corrupts a committed
artefact and shows up as an unexplained diff rather than as a
failure, so the redirect is automatic and opting out is explicit.

#### `epoch_clip`

An epoch cannot be shorter than the palette upload it covers, so a
clip meant to hold several of them has to be several seconds long.


### [`tests/geolith_model.py`](tests/geolith_model.py)

A model of the parts of the LSPC this project drives.

Both classes are independent transcriptions of geolith's
`src/geo_lspc.c`, not calls into the baker. `GeolithTileReader` mirrors
`geo_lspc_tpix` and the sprite pixel loop, including the flip handling.
`StreamPlayer` mirrors the VRAM write port plus the SCB1 decode at
`geo_lspc_sprcalc`, so replaying a baked stream through it reconstructs
the picture the emulator would put on screen.

#### `StreamPlayer`

Applies baked frame records to a VRAM model and reads back the grid.


### [`tests/test_adpcmb.py`](tests/test_adpcmb.py)

ADPCM-B encoder tests.

`YmfmDecoder` transcribes `adpcm_b_channel_clock` from the ymfm core
that geolith drives the YM2610 with. Encoding then decoding through it
proves the nibbles reconstruct the intended waveform on the chip that
will actually play them, rather than merely round-tripping through the
encoder's own model.

#### `TestAdaptiveRates`

The planner lowers the rate for long movies, so every rate it can pick is checked.


### [`tests/test_bake_epochs.py`](tests/test_bake_epochs.py)

#### `cut_clip`

Two scenes with nothing in common, joined by a hard cut.

#### `test_an_epoch_begins_at_the_cut`

Cuts are found in the strided palette sample, so a boundary

lands within one stride of the true cut rather than on it.

#### `test_a_cadence_still_subdivides_a_long_scene`

Subdivision survives, but only above the loader's minimum.

#### `TestEpochsGiveTheLoaderTime`

An epoch must outlast the upload of the one after it.

The player writes the next epoch's palettes into the other half of
CRAM a slice per frame. A boundary that arrives before that finishes
leaves the half holding the epoch before last, and the picture comes
back as a checkerboard of two scenes.


### [`tests/test_bake_run.py`](tests/test_bake_run.py)

#### `TestTheOverlayNamesTheRungActuallyUsed`

`auto` is a request, not an answer, and the cart must record the answer.


### [`tests/test_bakeargs.py`](tests/test_bakeargs.py)

#### `test_epochs_are_on_by_default`

No flag means the cadence is measured, not that epochs are off.


### [`tests/test_calibrate.py`](tests/test_calibrate.py)

Calibration tests.

Tile cost is a property of the content, so the sampler that measures it
is checked against a real decode rather than a stub.


### [`tests/test_cartridge.py`](tests/test_cartridge.py)

#### `_reading_bake`

Stand in for a bake that reports what it spent.


### [`tests/test_content.py`](tests/test_content.py)

#### `TestMovementFloor`

What counts as "this slot moved" is a property of the content.

A fixed threshold flagged 1% of slots on one source and 22% on another,
so scene-cut detection meant something different on every film. The floor
is measured as a high percentile of the movement the source actually
shows, which makes it mean the same thing everywhere.


### [`tests/test_crom.py`](tests/test_crom.py)

Tile packer tests.

`GeolithTileReader` is an independent transcription of `geo_lspc_tpix`
and the sprite pixel loop in geolith's `src/geo_lspc.c`. It reads the
byte-interleaved C-ROM the way the target emulator does, including the
flip handling, so a round trip through it proves the packed bytes render
as the source tile rather than merely matching the packer's own
arithmetic.


### [`tests/test_dither.py`](tests/test_dither.py)

#### `a_ramp_tile`

A 16x16 tile sweeping a gradient, the shape that bands worst.


### The encoder tests

Split by behaviour across [`tests/test_encode_frames.py`](tests/test_encode_frames.py), [`tests/test_encode_tolerance.py`](tests/test_encode_tolerance.py), [`tests/test_encode_budget.py`](tests/test_encode_budget.py), [`tests/test_encode_playback.py`](tests/test_encode_playback.py), [`tests/test_encode_epochs.py`](tests/test_encode_epochs.py), [`tests/test_encode_chroma.py`](tests/test_encode_chroma.py), [`tests/encodehelp.py`](tests/encodehelp.py).

#### `TestPlaybackFidelity`

Replays the baked stream through the LSPC model and compares pictures.

#### `half_moving`

Left half churns hard, right half holds still.

#### `gentle_drift`

Every slot changes every frame, by one shade.

#### `TestSeekEquivalence`

A keyframe must fully determine the screen.

The transport jumps to the nearest keyframe and plays on from there,
so if a keyframe record left any slot holding whatever the previous
scene put in it, every seek would land on a corrupted picture.

#### `TestPaletteEpochs`

Palettes refitted per scene, in alternating halves of CRAM.

A tile is an index into whichever bank its slot names, so a tile
interned under one epoch's palettes renders wrong under another's.
Epochs therefore never share dictionary entries, and the two halves
let the next epoch's colours be uploaded while the current one is
still on screen.

#### `four_scenes`

Four scenes with disjoint colour ranges.

One shared set has to span every scene while a per-epoch set
only spans its own, which is where refitting pays. With just two
scenes the halving for double buffering cancels the gain
exactly, so the effect needs more scenes than halves.

#### `TestEpochSchedule`

What the player needs in order to have colours ready in time.

#### `TestBudgetIsNotOverspent`

The controller limits spending; it deliberately does not allocate.

Letting it relax below the tier was measured twice and lost both
times, because tile spending is front-loaded and pacing against a
uniform budget relaxes exactly when spending is naturally light.
These pin the behaviour that survived.


### [`tests/test_epochs.py`](tests/test_epochs.py)

#### `test_the_minimum_follows_the_palette_count`

Half the palettes are uploaded per epoch, so more colours take longer.

#### `test_the_minimum_covers_the_upload_with_room_to_spare`

One upload time would leave nothing for the transport to redraw in.

#### `TestPaletteSampling`

How densely palettes are fitted should follow the epoch, not a constant.

The sample stride was every eighth frame regardless of anything else, so
the number of frames each epoch was fitted from drifted with the epoch
length, which is itself measured from the source. Targeting a sample
count per epoch keeps palette quality steady instead.


### [`tests/test_fixtiles.py`](tests/test_fixtiles.py)

Fix-layer glyph tests.

`geolith_fix_pixel` transcribes the S-ROM decode in geolith's
`geo_lspc_fixline_default`. A fix tile is 32 bytes holding 8x8 pixels at
four bits each, two pixels per byte with the low nibble on the left, and
the column pairs are stored in the order 0x10, 0x18, 0x00, 0x08. Reading
the packed bytes back through that order proves the glyphs land on
screen the way they were drawn.

#### `glyph`

The drawn pixels of one named glyph, read back out of the ROM.

#### `TestOverlayStyling`

The overlay reads as a seek bar rather than a row of blocks.


### The library tests

Split by behaviour across [`tests/test_fmv_open.py`](tests/test_fmv_open.py), [`tests/test_fmv_close.py`](tests/test_fmv_close.py), [`tests/test_fmv_playback.py`](tests/test_fmv_playback.py), [`tests/test_fmv_audio.py`](tests/test_fmv_audio.py), [`tests/test_fmv_corrupt.py`](tests/test_fmv_corrupt.py), [`tests/fmvhelp.py`](tests/fmvhelp.py).

Exercise the library as compiled C, against a stub of the hardware.

`src/fmv/fmv.c` is the half of the player that touches registers, so it
cannot run on the host without something standing in for them. The stub
in `hwstub/hw.h` is that stand-in, and it is deliberately not a faithful
mirror: the fix-source, palette-bank and bank latches are exposed only
through the functions that write them, with no read path at all. That is
what the board offers, and modelling it any other way would let a
save-by-reading defect pass, which is exactly the defect these tests
exist to keep out.

What runs here is the translation unit that ships, built by the host
compiler and called through ctypes, rather than a Python copy of it.

The blobs these tests hand it are packed in the host's byte order rather
than the cartridge's. Byte order is a property of the target, and what is
under test is the arithmetic that walks those blobs: which epoch covers a
frame, which bank an offset falls in, which slot a run starts at. The
cartridge's own big-endian packing is checked where it belongs, against
the emulator transcriptions.

#### `_stage`

Copy the library beside the stub, because `#include "hw.h"` is quoted.

A quoted include resolves against the directory of the file doing the
including before it looks at anything on the search path, so the real
header would win however the flags are ordered. Standing the sources
next to the stub is also how a developer holding an emitted folder
sees them: one directory, one header of each name.

### [`tests/test_frames.py`](tests/test_frames.py)

Source decode tests.

The decode tests drive the real ffmpeg binary against a generated clip
rather than a stubbed decoder, so the filter chain is checked as ffmpeg
actually applies it.

#### `test_a_taller_source_is_cropped_vertically`

4:3 on screen, not the raster's own 320:224

#### `test_a_matching_aspect_is_not_cropped`

A source already shaped like the screen, 4:3, survives whole.

#### `TestSourceAnalysis`

What the source itself says about how it should be baked.

#### `TestDisplayAspect`

The raster has non-square pixels, so cropping must target the screen.

An AES drives a 4:3 television with a 320x224 raster, which makes a
pixel 0.9333 as wide as it is tall. Cropping a source to the raster's
own ratio therefore squashes the picture by that much once it is
displayed; cropping to 4:3 is what arrives undistorted.


### [`tests/test_ladder.py`](tests/test_ladder.py)

#### `test_a_point_beaten_on_both_axes_is_dropped`

Costing more for a worse picture is never worth a rung.

#### `test_a_crowd_does_not_swallow_every_rung`

Fifty settings within a few percent must not use up the ladder.

Spacing is chosen in cost, not in list position, so a cheap outlier
still earns a rung even when it is outnumbered fifty to one.


### [`tests/test_mamecart.py`](tests/test_mamecart.py)

MAME cart packaging tests.

The dataarea names and load flags are the ones MAME's Neo Geo cart slot
looks for, taken from `src/devices/bus/neogeo/slot.cpp`. Packaging for a
second, independent emulator is the closest available stand-in for a
console: an encoding that both geolith and MAME agree on is far more
likely to be right on hardware than one confirmed by either alone.


### [`tests/test_measure_drift.py`](tests/test_measure_drift.py)

#### `flat_reconstruction`

Stub the reconstruction so a test controls what each frame looks like.

#### `baked`

Six frames whose offsets are their own index, so a stub can key on them.

#### `TestTiedMatches`

Consecutive frames are often pixel-identical on a static shot.

Keeping the first of those reports the player as hundreds of frames
behind when it is on time, because the tie runs backwards from the true
position. Among equally good matches the one nearest where the player
should be is the honest answer.


### [`tests/test_neocolor.py`](tests/test_neocolor.py)

Colour model tests.

`geolith_reference_rgb` is an independent transcription of geolith's
`geo_lspc_palconv` plus `geo_lspc_palgen_raw` from `src/geo_lspc.c`. It
decodes a CRAM word the way the target emulator does, so the assertions
below check the baker against the real decoder rather than against
another copy of the baker's own arithmetic.


### [`tests/test_neofile.py`](tests/test_neofile.py)

Cart container tests.

The field offsets and the byte-interleaved C region were recovered from
a known-good file produced by neosdconv and cross-checked against
geolith's `geo_neo_load`, so these tests assert against the format the
emulator actually parses rather than against the writer's own idea of it.


### [`tests/test_plan.py`](tests/test_plan.py)

Plan command tests.

The plan command is the surface a person reads before deciding whether
to trim a source, so it is driven end to end against a real clip.


### [`tests/test_probe.py`](tests/test_probe.py)

#### `measurer`

A stand-in for baking: reports what a tier would really cost.

#### `walk`

The rung a plain walk down the ladder would settle on.


### [`tests/test_quality.py`](tests/test_quality.py)

Quality tier selection tests.

The ladder decides how long a movie can be, so the arithmetic that picks
a tier is checked directly rather than through a bake.

#### `test_the_reference_tier_costs_about_one`

Calibration measures this rung, so it anchors the others.

#### `TestAudioFitsThePageCounter`

ADPCM-B addresses in 256-byte pages through a 16-bit register.

Page 65,536 does not exist, so filling the voice ROM to exactly
16 MiB puts the last page one beyond what the player can name.

#### `TestReferenceTier`

The top rung concedes nothing the encoder controls.

True lossless is not reachable on this hardware: a tile may use 15
colours and 83% of real tiles hold more than that, so the palette
step always loses something. What this tier guarantees is that every
avoidable compromise is switched off.

#### `TestAudioTakesWhatIsFree`

The voice ROM is its own chip, so audio quality costs no video.

Nothing about the sample rate touches the character ROM the picture
is built from, so the only reason to hold it down is the length of
the movie. It should therefore start at what the chip can do and
come down only when runtime demands it.

#### `TestAudioGrade`

Audio reported on the same eighteen-step scale as the picture.

The rate itself stays continuous, because audio competes with
nothing and rounding it down to a step could only throw quality
away. The grade exists so the two can be compared at a glance.

#### `TestPerSourceCurve`

The shape of the cost curve is a property of the content, not the ladder.

Measured across four sources, a setting's cost relative to the reference
varied by up to 2x at the extremes, so a ladder averaged over them
mispredicts any single source. Anchoring the curve at both ends of the
source itself removes that error.

#### `TestUnreachableHolds`

A hold that shows every source frame anyway saves nothing.

The baker refuses such a hold outright, so a planner that still offers
it hands back a tier that cannot be baked.

#### `TestTheCodeNeverTrims`

Shortening the film is the owner's call, never the baker's.

Every path that could be tempted to make a source fit by cutting it
has to do something else instead: refuse and say how much would have
to go, or give up a different budget.


### [`tests/test_timeline.py`](tests/test_timeline.py)

Exercise the player's pure core as compiled C, not as a reimplementation.

`src/fmv/timeline.c` holds every lookup and every piece of arithmetic the
68000 player does that has no hardware in it: which keyframe a seek
lands on, which cue covers a frame, which ADPCM page the audio wants,
how far along the seek bar sits, and which seek point C and D jump to.
A mistake in any of them is silent,
because the picture still appears and only the wrong part of it does.

These build the real translation unit with the host compiler and call
into it, so what is under test is the code that ships rather than a
Python copy of it that could drift.


### [`tests/test_verify_capture.py`](tests/test_verify_capture.py)

#### `TestStreamingIsBounded`

A feature-length preview must not be held in memory to search it.
