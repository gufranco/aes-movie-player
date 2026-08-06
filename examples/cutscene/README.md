# Cutscene example

A minimal game that plays a movie and carries on. It exists to prove one
claim: that a developer can take the folder the baker emits, drop it into
a project they already have, and get their machine back afterwards.

It is built the way a developer would build it. [`build.sh`](build.sh)
fetches a stock [ngdevkit-examples](https://github.com/dciabrin/ngdevkit-examples)
project at a pinned commit, copies the emitted bundle in, applies the
edits the bundle's own guide asks for, and runs the project's own `make`.
Nothing in this directory patches a linkscript, and nothing edits a file
the baker emitted. The only files touched are the project's `Makefile`
and its `rom.mk`, which is what those files are for.

## What it does

1. Uploads its own palette and clears the fix layer.
2. Plays the cutscene with `fmv_play`, skippable on any button or Start.
3. Draws its title screen, reporting whether the cutscene finished or was
   skipped.
4. Waits for Start to play it again.

Step 3 is the part that matters. It writes fix tiles and nothing else: no
palette upload, no register setup, no re-initialisation of any kind. If
the library had left the fix source, the palette bank or the LSPC mode
anywhere other than where the caller put them, the title screen would
come back wrong or not at all.

## Building it

```bash
uv --project tools run python -m aesmovie.bake \
    --source my-film.mkv --quality q17 --duration 30 \
    --build-dir build --preview build/preview.mkv --bundle build/bundle

BUNDLE=$PWD/build/bundle bash examples/cutscene/build.sh
```

The cartridge lands in `build/example/cutscene/build/rom/`.

## Checking it

```bash
PREVIEW=$PWD/build/preview.mkv bash examples/cutscene/verify.sh
```

That runs the cartridge in MAME past the end of the cutscene and asserts
two things: the screen has settled and stays settled, and it no longer
matches any frame of the movie. Together those say the movie played and
then got out of the way.

## What it does not cover

The example is video-only, which is the default path for a game that
already owns its sound driver. The soundtrack is exercised by the movie
cartridge this repository builds, not here.

It also needs a Neo Geo BIOS to run under MAME, which is why the check is
a local one rather than something CI can do.
