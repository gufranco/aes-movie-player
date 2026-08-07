# Releases

Generated from commit subjects by python-semantic-release, one entry per
version. What the project tried and rejected is in
[CHANGELOG.md](CHANGELOG.md); this file is only the version history.

<!-- version list -->

## v2.0.0 (2026-08-07)

### Bug Fixes

- **bundle**: Package both program ROMs, and check the movie draws
  ([`062a682`](https://github.com/gufranco/aes-movie-player/commit/062a682795576de0d3f4f501d1f2b5ed7f30a687))

- **ci**: Give the release notes somewhere to be written
  ([`2382082`](https://github.com/gufranco/aes-movie-player/commit/2382082d568c9bef683ff9b8d80d3bb007110332))

- **fmv**: Restore machine state the caller declares
  ([`a55b13b`](https://github.com/gufranco/aes-movie-player/commit/a55b13b5493927860d8e26e30720070cd0a5459d))

- **release**: Carry the library version with the package
  ([`998ce4f`](https://github.com/gufranco/aes-movie-player/commit/998ce4fc3acb35ca65c697da73b6c4e3e55becfa))

- **tools**: Refuse a capture match that is only a guess
  ([`1ed6656`](https://github.com/gufranco/aes-movie-player/commit/1ed665674941fd2df63285577965f639453b1e3a))

- **tools**: Stop mame taking over the display
  ([`4555c8b`](https://github.com/gufranco/aes-movie-player/commit/4555c8b951df5531ee200b28e2a2c0f569ca7289))

### Build System

- Let the linker place the movie stream
  ([`3e02f99`](https://github.com/gufranco/aes-movie-player/commit/3e02f99b0616b65ee4bf968c1708fd6aae48412a))

### Continuous Integration

- Assert the movie's own sound driver, not a stale comparison
  ([`d99cb71`](https://github.com/gufranco/aes-movie-player/commit/d99cb717f2490b7032a08b7cfaf9d5c07df01f2a))

- Give each job its own uv cache key
  ([`44c7ef4`](https://github.com/gufranco/aes-movie-player/commit/44c7ef4daad8b6f0e43228d571b019d7ceaea960))

- Move the actions off the deprecated node 20
  ([`d6e20e3`](https://github.com/gufranco/aes-movie-player/commit/d6e20e32ceaec57ecf3e27b1e927600896788d38))

- Pin the actions to exact tags
  ([`42e2fa1`](https://github.com/gufranco/aes-movie-player/commit/42e2fa124af91fb5ec561a63e3b7a7ab391b799b))

### Documentation

- **changelog**: Record the blank screen and how it was misread
  ([`3a34e70`](https://github.com/gufranco/aes-movie-player/commit/3a34e70ae7fcc8383eda9e6793df8753ffd7a6e6))

- **changelog**: Record what the split cost to get right
  ([`1cc7315`](https://github.com/gufranco/aes-movie-player/commit/1cc73157735cddc2c3b5ee143f11559e2c969ee2))

- **readme**: Correct the test count
  ([`a33e20c`](https://github.com/gufranco/aes-movie-player/commit/a33e20c9b233c37f697430a3306be0f29e11b68b))

- **readme**: Promise the library from 2.0
  ([`a8b305a`](https://github.com/gufranco/aes-movie-player/commit/a8b305a2a75703bc16dabb59b3778a1af84fcc86))

- **readme**: Record the library running on a board
  ([`ae6493e`](https://github.com/gufranco/aes-movie-player/commit/ae6493e0030ed30c184d65b5d7ef1f07de1a172d))

- **readme**: Write for both audiences
  ([`b7e4021`](https://github.com/gufranco/aes-movie-player/commit/b7e4021ae1af9fe4ddcd52dfaae650527d2deb25))

### Features

- **baker**: Emit a drop-in bundle for game projects
  ([`3c96e46`](https://github.com/gufranco/aes-movie-player/commit/3c96e46c9bf16be8b5df8157acc9e1157a9d2806))

- **baker**: Make room for the caller's own tiles
  ([`f58abb7`](https://github.com/gufranco/aes-movie-player/commit/f58abb799aa0f0a52b0cadb965a021e4ab37167c))

- **examples**: Prove the integration with a real project
  ([`76d8e09`](https://github.com/gufranco/aes-movie-player/commit/76d8e090c33ee7b1c398890360593c9725273609))

- **fmv**: Prove the soundtrack from a bundle
  ([`a9fb04b`](https://github.com/gufranco/aes-movie-player/commit/a9fb04b82fe3dac9a2acc3120217f9601adaefc3))

### Refactoring

- **fmv**: Put the player's state behind accessors
  ([`3dc7ab0`](https://github.com/gufranco/aes-movie-player/commit/3dc7ab053d0ece4ee3e44821e5c6987396234508))

- **fmv**: Split the renderer into a library other games can use
  ([`a6b73f7`](https://github.com/gufranco/aes-movie-player/commit/a6b73f7defb0e26bb92aae0cb751a1a60a1d7ce6))

### Testing

- **fmv**: Run the library on the host against a hardware stub
  ([`5578367`](https://github.com/gufranco/aes-movie-player/commit/5578367d324e5f4edf73a982c2eb8e08ef24796d))


## v1.0.0 (2026-08-05)

### Bug Fixes

- **tools**: Make the search reject rescued rungs and stop early
  ([`ffeafcc`](https://github.com/gufranco/aes-movie-player/commit/ffeafcc1cc53cff1fa8666ca633e2af06f772b84))

### Continuous Integration

- Derive the version from the commits
  ([`08dafd6`](https://github.com/gufranco/aes-movie-player/commit/08dafd6840faf40f6a949968b43f08649104f1d0))

- Let a release force its bump level
  ([`f66efff`](https://github.com/gufranco/aes-movie-player/commit/f66efff717fb135bd41ba6a6b8592c51010d1ff6))

### Documentation

- **readme**: Describe the search as it now works
  ([`2b4714f`](https://github.com/gufranco/aes-movie-player/commit/2b4714faac70789731e75ba1500f9f0176c9eaf2))

- **readme**: State the region fact and what 1.0 promises
  ([`7f0805b`](https://github.com/gufranco/aes-movie-player/commit/7f0805b4b992de520a61fef5f61bb7400e19ce3f))

- **readme**: Verify a cartridge at the edge of the C-ROM
  ([`382c713`](https://github.com/gufranco/aes-movie-player/commit/382c713f391f9456fe9aff82d0c71a19ba154a5b))

### Features

- **tools**: Remove the tier guess and default to measuring
  ([`4033da7`](https://github.com/gufranco/aes-movie-player/commit/4033da78a01e97d31a5c6d9992d9d863c26c4219))

### Breaking Changes

- **tools**: --quality auto is removed. Use --quality search, which is now the default, or name a
  rung.


## v0.1.0

First tagged version. Plays a baked movie from cartridge on real AES and MVS
hardware, with a measured quality ladder, per-scene palettes, subtitles and a
working transport.
