# The family standard

One standard, carried identically by every repository in the family. It records
the decisions that were expensive to reach, so a repository does not reach them
again and a running one does not drift away from them quietly.

The family plays full-motion video on consoles that were never meant to show
it, on the original hardware. Where two members differ, the difference is one
the hardware forces.

| Member | What it is | Kind |
|:--|:--|:--|
| [neogeo-media-player](https://github.com/gufranco/neogeo-media-player) | A full-screen movie with sound on a Neo Geo AES or MVS, and a library that plays one inside another game | Player |
| [smsgg-media-player](https://github.com/gufranco/smsgg-media-player) | A full-screen film on a Sega Master System or a Game Gear, each in its own mode, its tiles paged through VRAM as it plays | Player |
| [fmv-core-python](https://github.com/gufranco/fmv-core-python) | The baker and measurement code both players share: decoding, colour, dither, the regression set, capture comparison, the write-timing walk, the test helpers | Core |

## How a repository joins

Copy this file in unchanged, follow it, and add the repository to the table above
in every member in the same task. Everything above the closing line is shared
and must match across the members. Each player checks its copy against the one
in its `fmv-core-python` submodule, so a drifted copy fails that player's suite:

```bash
diff <(sed '/^---$/q' FAMILY.md) <(sed '/^---$/q' fmv-core-python/FAMILY.md)
```

A rule that needs changing is changed in every member in the same task. A copy
that has drifted is worse than no copy, because a reader trusts it.

## The rule above every other rule

**The picture on the original hardware wins every decision.** When it pulls
against speed, a smaller diff, a nicer interface or finishing today, the
hardware wins and the cost is reported rather than negotiated.

- **An emulator is not evidence about the console.** Emulators accept writes at
  any rate and show a perfect picture. A clean emulator run, a green suite and a
  good-looking capture are evidence about an emulator.
- **A change the console can disagree with is unverified until it has run on
  one.** That covers the transfer loop, port and register access, the bank
  mapper, the interrupts and the header. Say so in the change and ask for the
  run.
- **A documented figure binds over a looser measured one.** Looser is never a
  reason.

## What every player does

These are the owner's requirements for every player, present and future. A
player that does not meet one yet lists the gap in its own state section below
the closing line, and closing the gap is planned work, never a reason to drop
the requirement.

- **The same features in every player.** A feature one player has, every
  player has, and the READMEs describe them in the same words under the same
  headings. A feature a console cannot carry for a technical reason stays in
  that player's README feature table, marked as not possible, with the reason
  in one sentence: the hardware limit, its figure and its source. Not built yet
  is never written as not possible.
  The table is kept once, per language, in `fmv-core-python/features/`, and
  each player's suite fails when its README's copy differs from it.

- **Alike in everything the hardware does not force apart.** Beyond the
  features, the members match in layout, file and module names, command-line
  flags and their defaults, controls, the menu, messages, the build and test
  commands, the tooling configuration, the workflows and the documents. A
  difference is allowed only when the console forces it, and the player's
  state section names it with the hardware reason. A difference found with no
  such reason is a gap, closed by moving the weaker member onto the stronger
  one.
- **The picture fills the screen.** A source of any shape is scaled until it
  covers the console's raster and then cropped, so a wide film loses its sides.
  The crop follows the shape a television shows, pixel shape included: a
  player crops to the raster's displayed aspect, never to its pixel count,
  so a circle in the film stays round on the console. A console whose pixel
  shape no source gives is taken as square.
  Black bars baked into a source file are detected and cropped before scaling.
  No player adds letterboxing or padding, because bars cost tiles and transfer
  like any other picture.
- **Every console a player serves gets its own cartridge.** Owner's
  instruction, 2026-10-17: where one player serves consoles that share a
  design, such as the Master System and the Game Gear, the baker builds a
  native cartridge for each, and each uses its console fully: its own screen,
  colours and sound, never the mode the weaker console imposes.
- **Perceived picture quality comes before frame rate.** When the two compete
  for bytes, slots or cycles, the picture wins.
- **Every default is the best picture.** Owner's instruction, 2026-11-02: a
  baker's default for every setting that changes the picture is the one that
  measured best on the blurred error and on the sheets. Bake time is never a
  reason to default to less; a faster setting stays available as a flag.
- **Sound, the way the console can play it, with no added hardware.** Every
  player carries the film's sound using only what the stock console and a
  standard cartridge provide.
- **A silent build.** The baker can leave sound out, and every byte and cycle
  sound would have used goes to a longer or better picture.
- **The whole cartridge.** A player can fill the largest cartridge its
  console's standard mapper or board addresses, with no extra hardware on the
  cartridge beyond that standard. The ceiling is the documented one.
- **Quality steps down until the film fits.** Every player carries sound, and
  the baker starts at the best picture and sound the console can show, then
  steps both down a measured ladder, one rung at a time, until the film fits
  the cartridge. A short film keeps the top rung; a long one goes down only as
  far as it must. Rungs are settled by baking, never by a fixed table, and the
  ladder keeps getting better as the players do.
- **A menu in the style of a media player.** Before and during playback the
  viewer has play and pause, seek backward and forward, restart and stop, a
  position bar with elapsed and total time, and sound on and off where there
  is sound. The controls show on input and get out of the picture's way while
  it plays.
- **One menu, as alike as the consoles allow, in function and in look.**
  Owner's instruction, 2026-10-17: every player's menu is the Neo Geo's,
  reproduced as closely as each console can draw it. The same controls do the
  same things, and the panel has the same parts in the same order: an opaque
  dark panel with a lighter top edge, a seek bar with end caps and a knob, and
  under it the state icon, then the speed where the console can play faster,
  then MUTE when sound is off, then the elapsed and total time. A console that
  cannot draw a part at the Neo Geo's size draws it smaller in the same place,
  never differently, and its state section names the limit, such as the
  Master System's eight sprites a line, with its figure and source. A change
  to one player's menu is made in every player in the same task.
- **A menu that costs the picture is off by default.** Owner's instruction,
  2026-10-17: where drawing the menu takes something from the film, as the
  Master System and Game Gear menu takes 4 of the film's 32 colours, the
  baker leaves it out unless asked, and asking for it prints a warning that
  the picture will lose quality. The controls work either way; only what is
  drawn over the picture changes.

## How a new member starts

1. Read this file, then every player end to end, before writing anything.
2. Name it `<console>-media-player`, its baker package `<console>media`, and
   its environment variables `<CONSOLE>MEDIA_*`.
3. Collect the console's binding numbers from the manufacturer's documents
   into its `AGENTS.md`, each with its source, before the first write to a
   port.
4. Take the core as a submodule on day one, and add to the core rather than
   to the player whatever the hardware does not force.
5. Build in a pinned Docker image, with the same Makefile targets, hooks, CI
   and release as the other players.
6. Meet every requirement in "What every player does", or list each gap in the
   state section.
7. Add the repository to the member table in every member in the same task.

## The authority ladder

Every hardware question is answered by the highest rung that has an answer, and
a lower rung never overrules a higher one.

1. **The manufacturer's documentation.** Cited with the page or section it came
   from.
2. **A run on the original hardware.** A board, a console or a handheld running
   the build in question, reported with what was run, what was seen, and the
   model and video chip revision it ran on. Timing differs between revisions:
   the Master System 2's VDP drops rapid palette writes that the Master System
   1 and the Game Gear accept, per MacDonald's VDP notes, so a run on one
   revision does not settle another.
3. **An emulator's source, read.** The decoder or core that implements the
   behaviour, cited by file and function, never a prose summary of it.
4. **Anything else.** A community measurement or another implementation, cited
   as what it is and never the sole support for a figure a manufacturer would
   have printed.

When two rungs disagree and the ones above are silent, the answer is unknown. It
is written down with the run that would settle it, and no member picks the more
convenient figure and moves on.

## What lives once, and what each player keeps

Code that the hardware does not force exists once, in `fmv-core-python`, and
both players use it. A player that keeps its own copy of a shared concern is a
defect, because the two copies drift and the better one stops reaching the
other player.

| In the core | In each player |
|:--|:--|
| Decoding a source, probing it, refusing a failed or torn decode | The stream format and the player that replays it |
| Range-checked command-line values | The console's write rules and their binding numbers |
| Colour distance, the blurred error, the ordered dither | How tiles reach the screen: resident or paged |
| The clip manifest, its fetch and verification, the regression-set scaffolding | Sound, where the console carries it |
| Capture comparison against the source | The cartridge layout and its packaging |
| Search windows, scoring and ties | What the search tunes, while the two still differ |
| The cheapest-path write-timing walk, with a reader per instruction set | The listing that walk reads, and the floors it holds |
| Seeded test fakes, the required-tool marker, the golden-test shape | The hardware gates that run the player's own code |

When both players have a module, the better-tested and better-guarded one moves
to the core and the other player adapts to it.

Owner's instruction, 2026-10-17: the consoles one player serves share as much
code as they can, so that nothing differs between their cartridges except what
the hardware forces, and every player shares as much as it can with the rest
of the family. A difference between two consoles is data, such as a colour
lattice, a screen size or a port, passed to one code path, never a second
path. Integrity and reuse across the family are checked on every change: a
fix made in one member is looked for in every other member in the same task.

## How a player depends on the core

The core is a git submodule on the import path, at the repository root under its
own name, never a published package:

```bash
git clone --recurse-submodules https://github.com/gufranco/<player>.git
```

That choice has a price, paid deliberately:

- **A source archive cannot carry a submodule.** The download-zip link produces a
  checkout that cannot run. The README says so at the install step.
- **A submodule pins a commit, and a pin goes stale.** A weekly job in each
  player reports how many commits its pin is behind the core's head, and a pin
  is moved because the report says so.
- **Moving a pin is a change to the player's behaviour until shown otherwise.**
  The golden test and the regression set run against the newer core before the
  bump is committed. When an output changes, find the core commit that changed
  it and why before touching anything that records what the output should be.

## What every repository carries

| File | Holds |
|:--|:--|
| [`README.md`](README.md) | The document for a person: what it is, how to build and run it, and why it can be trusted. Every player's README has the same sections in the same order, opens with an animated GIF of at least five seconds of the shared demo film playing from that player's cartridge in an emulator, and has translations |
| `README.ja.md`, `README.zh-Hans.md`, `README.zh-HK.md` | Japanese, Simplified Chinese and Hong Kong Traditional Chinese translations of the README, each translated from the English file, keeping its headings, code blocks and links, with a language switcher under the tagline of every version, above the badges |
| `AGENTS.md` | The engineering contract: the hardware's binding numbers with their sources, the gates, the things that bite, what is not done |
| `FAMILY.md` | This file, identical in every member |
| `DESIGN.md` | Why each part of the code is shaped as it is, with the measurements behind it. Source files carry none of this |
| [`CHANGELOG.md`](CHANGELOG.md) | What was tried, measured and rejected, and what each failure cost |
| [`RELEASES.md`](RELEASES.md) | The version history, generated from commit subjects |
| `Dockerfile` | A player's toolchain image: base by digest, packages from a dated snapshot, every third-party package by exact version and SHA-256 |
| `Makefile` | A player's `rom`, `analyse`, `timing`, `hooks`, `shell`, `clean`, `distclean`, each running in the image as the calling user. The core carries `hooks` and `clean` |
| `.githooks/pre-commit` | Format, lint, types and tests on every commit, plus a player's hardware gates when a staged path can change the player |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | The same gates on every push and pull request, and the commit-subject check |
| [`.github/workflows/release.yml`](.github/workflows/release.yml) | Gates in a read-only job; only the publish job holds a write token |
| [`.github/dependabot.yml`](.github/dependabot.yml) | Weekly grouped updates for actions, the Python lockfile and the Docker base |

## How the picture is judged

- **Against one fixed reference.** A variant is scored against the source, never
  against its own output.
- **By eye as well as by number.** A dither moves pixels away from the source on
  purpose, so a per-pixel error always scores it as loss. It is judged by the
  error after the same blur on both sides and by a rendered sheet looked at
  beside the source, and both must agree.
- **The blur averages light, as the eye does.** It runs on linear light, and the
  Oklab error is taken after it. A blur taken in Oklab reads a dither of black
  and a dark level as darker than it looks, and scored a flat grey of the wrong
  brightness above a correct dither in every dark scene measured on
  2026-10-18. For the same reason an ordered dither between two levels of a
  colour channel takes each by its share of light, never by its code value.
  The core's two-entry palette mix weighs by Oklab distance: weighing it by
  light measured 0.3% to 1.6% worse on the Game Gear, because the entries it
  mixes sit close together. The Neo Geo draws its dither through the core's
  sixteen-pick pattern dither instead, which beat the two-entry mix and four
  picks on all six of its films; on the Master System and the Game Gear it lost or
  split in every form measured, so they keep the two-entry mix.
- **Nothing aimed at a CRT.** A dither is allowed when it raises the picture's
  quality on a sharp screen. No composite model and no technique that needs a
  display to blend colours the console cannot show.
- **On more than one film.** A parameter fitted to one clip is a fit, not a
  setting. Every encoder change is measured on the regression set: films of
  different kinds, fetched by manifest and verified by SHA-256, never committed.
- **Render before reasoning about a screen.** A capture settles in one look what
  an argument about which write reaches which table can get wrong for weeks.

## How the work is done

- **Every requirement the owner states is written into this file in the same
  task**, in every member, so no member has to be told twice.
- **No member is a port of another.** Every repository is a member of one
  family of tools, and the text says so. Never describe one as a port, fork,
  translation or derivative of another, in any language, and never tell
  which member came first: work moves between the members in every
  direction, and more consoles will join.
- **Capture before asking.** When something is wrong on screen, record the
  emulator, cut the recording into frames and read them. Ask only when that
  loop has run and cannot settle the question, and say what it showed.
- **A measurement answers what happened, never on its own what is better.**
  Render it and look before quoting a number for a change.
- **An emulator never takes the screen.** A scripted run is headless: MAME
  with `SDL_VIDEODRIVER=dummy` and `-window -video none -sound none`, because
  MAME starts full screen on macOS and `-video none` alone still opens a
  window; RetroArch through `open -g -j`; mednafen with `-video.fs 0 -sound 0`,
  minimised. A run the owner asked to watch opens windowed and minimised,
  never full screen.
- **MAME is a cross-check, never the first witness.** Its BIOS and
  configuration defaults have produced failures and false positives, so the
  evidence comes from another emulator first: geolith for the Neo Geo,
  mednafen or Emulicious for the Master System.
- **Private projects are never named** in a public member: not their name, path,
  remote or functions. A figure taken from one is cited by its documented
  source or by a run on hardware.
- **Every member is a solo repository** and lands on `main` directly, after
  every gate passes.
- **The demo film is the Sintel trailer** by the Blender Foundation, CC BY 3.0,
  credited wherever it appears. A demo GIF shows the cartridge's own stream:
  a capture from the emulator running it, or the replay oracle's drawing of
  that stream once a headless capture has matched it pixel for pixel
  outside the player's overlay. It is never a render of the baker's preview.
- **A preview video plays everywhere and keeps every pixel.** A baker's
  `.mp4` preview goes through `fmvcore.video`: near-lossless H.264 High at an
  even nearest-neighbour enlargement, checked to decode back within the bound
  measured over the console's whole colour set, 5 levels unless a player
  measured more; a `.mkv` is lossless FFV1.
- **A player's demos match frame for frame.** When a player carries more
  than one console, every console's demo is baked from the same window of
  the demo film with the same settings, drawn the same way and cut to the
  same fields, so each GIF has the same frame count and timing and the same
  frame shows the same moment. One committed script makes them all. They are
  made again after any change to the picture, and only once the consoles'
  pictures are perceptually alike: a console whose picture looks visibly
  worse is a defect to fix first (owner, 2026-10-17).
- **Every file is covered and every test is end to end** (owner,
  2026-10-17). Coverage is 100% of the statements and branches of every
  file, the scripts included, and a test drives the code the way a bake or a
  console does: real files, the real decoder, the built ROM on a Z80 or an
  emulator, with no mock of the family's own code. A member below either bar
  lists the gap in its state section until it closes.

## Verification

- **A check nobody has seen fail is not known to work.** Every gate is driven
  once against input that should fail it before it is trusted.
- **Silence and success produce the same output.** A check that found no files,
  no listings or no clips exits zero like one that examined everything. Print
  what was examined, and fail when it was nothing.
- **Nothing is skipped quietly.** A test that needs a tool, a built ROM or the
  films skips without it, and fails when the matching `*_REQUIRED=1` is set,
  which CI and the pre-commit hook set.
- **A passing check expires when what it covers changes.** Run it again after
  touching anything within its reach.
- **Measure before claiming.** Every number in a document is one somebody ran.

## Conventions that are not negotiable

| Thing | Rule |
|:--|:--|
| Baker language | Python, at the version the core pins, managed with `uv` and a committed lockfile |
| Player language | C and assembly for the console's CPUs, built only in the pinned image |
| Comments | None in source and no docstrings. Names carry the meaning; `DESIGN.md` carries the reasoning |
| Size | Functions under 30 lines, files under 500 |
| Types and lint | `mypy` strict, `ruff` clean, magic numbers named outside tests |
| Static analysis | `cppcheck` at exhaustive level on the player, zero findings |
| Test shape | Arrange, Act, Assert, each opened by its bare marker, one act |
| Test data | Values that do not matter come from the core's seeded fakes |
| Coverage | 100% of statements and branches in every file, the scripts included; the floor each member's CI enforces never drops, and rises to 100% as its gap closes |
| Commits | Conventional Commits, subject at most 50 characters, lowercase start |
| Actions | Pinned by full commit SHA |
| Films | Fetched and verified by manifest, never committed |
| ROMs | Never committed, and never published when built from someone else's work |
| Names | Players are `<console>-media-player` with a `<console>media` package; the core is `fmv-core-python` with the `fmvcore` package |
| Language | Everything committed is English, except the README translations |
| Licence | MIT in every member, one `LICENSE` file at the root. Code is never copied from a project under a licence MIT cannot carry, such as GPL; such a project is read for ideas only and cited in the development log |
| Builds | Docker for every player build, in an image pinned by digest, run as the calling user; no host toolchain path |

---

*Everything above this line is identical in every member. A member may add
sections below it about its own state, and nothing may be added above it that
the others do not also get.*

## The state of this repository

neogeo-media-player is the Neo Geo member. Its tile dictionary is resident in
character ROM, so its encoder settles a rung on a 35-rung quality ladder by
real bakes rather than paging patterns, and its sound is ADPCM-B samples in
their own V-ROM. It decodes, scores, verifies films and measures captures
through `fmv-core-python`.

Gaps against "What every player does" (as of 2026-10-17):

- Coverage per file and the share of end-to-end tests have not yet been
  measured against the 2026-10-17 requirement of 100% in every file and
  end-to-end tests; CI enforces 95%.

Differences the hardware forces:

- A silent build gives the picture nothing. `--silent` leaves sound out of
  the cartridge and `FMV_AUDIO=no` leaves it out of a library bundle, but
  sound lives in its own V-ROM, so leaving it out frees no character ROM for
  the picture.
