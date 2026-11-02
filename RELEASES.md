# [3.3.0](https://github.com/gufranco/neogeo-media-player/compare/v3.2.0...v3.3.0) (2026-11-02)


### Features

* **dither:** dither by default, sixteen picks ([d7de9f2](https://github.com/gufranco/neogeo-media-player/commit/d7de9f2ae3594d7fc74253fbf508cf022d1586bb))
* **preview:** near-lossless video for any player ([11ba949](https://github.com/gufranco/neogeo-media-player/commit/11ba949a3d3d938c66d059b660a1ae721f59eb83))

# [3.2.0](https://github.com/gufranco/neogeo-media-player/compare/v3.1.0...v3.2.0) (2026-11-02)


### Features

* **palettes:** migrate entries, pattern dither ([8e7fef3](https://github.com/gufranco/neogeo-media-player/commit/8e7fef356a70e14193c2c93f07bdba5d97aec61f))

# [3.1.0](https://github.com/gufranco/neogeo-media-player/compare/v3.0.0...v3.1.0) (2026-10-30)


### Features

* **audio:** pre-condition the soundtrack ([6d30253](https://github.com/gufranco/neogeo-media-player/commit/6d30253289d512e0ecf1b03a96f3c49f16cb1b48))

# [3.0.0](https://github.com/gufranco/neogeo-media-player/compare/v2.0.0...v3.0.0) (2026-10-24)


### Bug Fixes

* **baker:** refuse a seek interval under a frame ([6506f03](https://github.com/gufranco/neogeo-media-player/commit/6506f033e5d8d1ac6df5fb571d898bfa677d1a91))
* count all 40 blank lines of the frame ([0a55bc6](https://github.com/gufranco/neogeo-media-player/commit/0a55bc6bdf813eeeb767ebdc6bed79d97765ce03))
* **dither:** break palette ties as the plain path ([e04c907](https://github.com/gufranco/neogeo-media-player/commit/e04c90794e2011c1bff1250c19bcecc18dd9354d))
* **docker:** bump the pruned ngdevkit deb ([ce58326](https://github.com/gufranco/neogeo-media-player/commit/ce58326d3a632389249128a61a3e1e6d5c22c5f2))
* **docker:** stop pinning the bootstrap CA bundle ([aed8e45](https://github.com/gufranco/neogeo-media-player/commit/aed8e456faec3939d3cbdff8f54849a3756ccc71))
* launch every emulator headless ([35661d4](https://github.com/gufranco/neogeo-media-player/commit/35661d4862bb95795bf7b2d66da8b1f6314389af))
* **palettes:** rank shortlist candidates stably ([2d2eeda](https://github.com/gufranco/neogeo-media-player/commit/2d2eeda8851644ba4638ffee36df3b8796869720))
* take the synthetic film from the core ([557d951](https://github.com/gufranco/neogeo-media-player/commit/557d951a2f8824bcddfc9a75eaa79eb8289fcb31))
* turn the bios eye-catcher off ([3d818d7](https://github.com/gufranco/neogeo-media-player/commit/3d818d7e2e899b72bf46829f4585e3ad5a25acdf))


### Features

* **baker:** align cartridge flags with the family ([b66ad9f](https://github.com/gufranco/neogeo-media-player/commit/b66ad9fb4868c9a992c7fb0df0e44098d19ebe7c))
* check every command-line value's range ([787290a](https://github.com/gufranco/neogeo-media-player/commit/787290a00041e37e0f1ad219c26e2e2ab746a5b9))
* fault on corrupt streams, add stop and mute ([92578f5](https://github.com/gufranco/neogeo-media-player/commit/92578f570b856704f41f9f40d2af083eb3474270))
* measure a cartridge against its source film ([a71bae3](https://github.com/gufranco/neogeo-media-player/commit/a71bae31925c5d6c4a6e36bd19babd2bfae3b6e9))
* measure denoise on the film in the search ([59832a7](https://github.com/gufranco/neogeo-media-player/commit/59832a74506bc981c8bea12b35de0852927f6f75))
* **palettes:** mix only a pair that brackets ([49bee23](https://github.com/gufranco/neogeo-media-player/commit/49bee232e46c3f01be0a491d38e52a7390417cf2))
* **player:** seek between baked points ([1357057](https://github.com/gufranco/neogeo-media-player/commit/13570578fab0846e90e05239003ad23696bf1221))
* report the family's blurred error per bake ([a0badda](https://github.com/gufranco/neogeo-media-player/commit/a0badda5cf0a3497a6d8451501becc9a0b55439a))
* walk vram timing across the whole player ([23eb87d](https://github.com/gufranco/neogeo-media-player/commit/23eb87dd7a117c468c211640b0d781e19f61fe9a))


### BREAKING CHANGES

* **baker:** --fit is removed from the cartridge, bake and plan
commands, and report.json renames stream_banks and stream_bytes to
banks and bytes.

# Releases

Generated from commit subjects by semantic-release, one entry per
version. What the project tried and rejected is in
[CHANGELOG.md](CHANGELOG.md); this file is only the version history.

<!-- version list -->

## v2.0.0 (2026-08-07)

### Bug Fixes

- **bundle**: Package both program ROMs, and check the movie draws
  ([`062a682`](https://github.com/gufranco/neogeo-media-player/commit/062a682795576de0d3f4f501d1f2b5ed7f30a687))

- **ci**: Give the release notes somewhere to be written
  ([`2382082`](https://github.com/gufranco/neogeo-media-player/commit/2382082d568c9bef683ff9b8d80d3bb007110332))

- **fmv**: Restore machine state the caller declares
  ([`a55b13b`](https://github.com/gufranco/neogeo-media-player/commit/a55b13b5493927860d8e26e30720070cd0a5459d))

- **release**: Carry the library version with the package
  ([`998ce4f`](https://github.com/gufranco/neogeo-media-player/commit/998ce4fc3acb35ca65c697da73b6c4e3e55becfa))

- **tools**: Refuse a capture match that is only a guess
  ([`1ed6656`](https://github.com/gufranco/neogeo-media-player/commit/1ed665674941fd2df63285577965f639453b1e3a))

- **tools**: Stop mame taking over the display
  ([`4555c8b`](https://github.com/gufranco/neogeo-media-player/commit/4555c8b951df5531ee200b28e2a2c0f569ca7289))

### Build System

- Let the linker place the movie stream
  ([`3e02f99`](https://github.com/gufranco/neogeo-media-player/commit/3e02f99b0616b65ee4bf968c1708fd6aae48412a))

### Continuous Integration

- Assert the movie's own sound driver, not a stale comparison
  ([`d99cb71`](https://github.com/gufranco/neogeo-media-player/commit/d99cb717f2490b7032a08b7cfaf9d5c07df01f2a))

- Give each job its own uv cache key
  ([`44c7ef4`](https://github.com/gufranco/neogeo-media-player/commit/44c7ef4daad8b6f0e43228d571b019d7ceaea960))

- Move the actions off the deprecated node 20
  ([`d6e20e3`](https://github.com/gufranco/neogeo-media-player/commit/d6e20e32ceaec57ecf3e27b1e927600896788d38))

- Pin the actions to exact tags
  ([`42e2fa1`](https://github.com/gufranco/neogeo-media-player/commit/42e2fa124af91fb5ec561a63e3b7a7ab391b799b))

### Documentation

- **changelog**: Record the blank screen and how it was misread
  ([`3a34e70`](https://github.com/gufranco/neogeo-media-player/commit/3a34e70ae7fcc8383eda9e6793df8753ffd7a6e6))

- **changelog**: Record what the split cost to get right
  ([`1cc7315`](https://github.com/gufranco/neogeo-media-player/commit/1cc73157735cddc2c3b5ee143f11559e2c969ee2))

- **readme**: Correct the test count
  ([`a33e20c`](https://github.com/gufranco/neogeo-media-player/commit/a33e20c9b233c37f697430a3306be0f29e11b68b))

- **readme**: Promise the library from 2.0
  ([`a8b305a`](https://github.com/gufranco/neogeo-media-player/commit/a8b305a2a75703bc16dabb59b3778a1af84fcc86))

- **readme**: Record the library running on a board
  ([`ae6493e`](https://github.com/gufranco/neogeo-media-player/commit/ae6493e0030ed30c184d65b5d7ef1f07de1a172d))

- **readme**: Write for both audiences
  ([`b7e4021`](https://github.com/gufranco/neogeo-media-player/commit/b7e4021ae1af9fe4ddcd52dfaae650527d2deb25))

### Features

- **baker**: Emit a drop-in bundle for game projects
  ([`3c96e46`](https://github.com/gufranco/neogeo-media-player/commit/3c96e46c9bf16be8b5df8157acc9e1157a9d2806))

- **baker**: Make room for the caller's own tiles
  ([`f58abb7`](https://github.com/gufranco/neogeo-media-player/commit/f58abb799aa0f0a52b0cadb965a021e4ab37167c))

- **examples**: Prove the integration with a real project
  ([`76d8e09`](https://github.com/gufranco/neogeo-media-player/commit/76d8e090c33ee7b1c398890360593c9725273609))

- **fmv**: Prove the soundtrack from a bundle
  ([`a9fb04b`](https://github.com/gufranco/neogeo-media-player/commit/a9fb04b82fe3dac9a2acc3120217f9601adaefc3))

### Refactoring

- **fmv**: Put the player's state behind accessors
  ([`3dc7ab0`](https://github.com/gufranco/neogeo-media-player/commit/3dc7ab053d0ece4ee3e44821e5c6987396234508))

- **fmv**: Split the renderer into a library other games can use
  ([`a6b73f7`](https://github.com/gufranco/neogeo-media-player/commit/a6b73f7defb0e26bb92aae0cb751a1a60a1d7ce6))

### Testing

- **fmv**: Run the library on the host against a hardware stub
  ([`5578367`](https://github.com/gufranco/neogeo-media-player/commit/5578367d324e5f4edf73a982c2eb8e08ef24796d))


## v1.0.0 (2026-08-05)

### Bug Fixes

- **tools**: Make the search reject rescued rungs and stop early
  ([`ffeafcc`](https://github.com/gufranco/neogeo-media-player/commit/ffeafcc1cc53cff1fa8666ca633e2af06f772b84))

### Continuous Integration

- Derive the version from the commits
  ([`08dafd6`](https://github.com/gufranco/neogeo-media-player/commit/08dafd6840faf40f6a949968b43f08649104f1d0))

- Let a release force its bump level
  ([`f66efff`](https://github.com/gufranco/neogeo-media-player/commit/f66efff717fb135bd41ba6a6b8592c51010d1ff6))

### Documentation

- **readme**: Describe the search as it now works
  ([`2b4714f`](https://github.com/gufranco/neogeo-media-player/commit/2b4714faac70789731e75ba1500f9f0176c9eaf2))

- **readme**: State the region fact and what 1.0 promises
  ([`7f0805b`](https://github.com/gufranco/neogeo-media-player/commit/7f0805b4b992de520a61fef5f61bb7400e19ce3f))

- **readme**: Verify a cartridge at the edge of the C-ROM
  ([`382c713`](https://github.com/gufranco/neogeo-media-player/commit/382c713f391f9456fe9aff82d0c71a19ba154a5b))

### Features

- **tools**: Remove the tier guess and default to measuring
  ([`4033da7`](https://github.com/gufranco/neogeo-media-player/commit/4033da78a01e97d31a5c6d9992d9d863c26c4219))

### Breaking Changes

- **tools**: --quality auto is removed. Use --quality search, which is now the default, or name a
  rung.


## v0.1.0

First tagged version. Plays a baked movie from cartridge on real AES and MVS
hardware, with a measured quality ladder, per-scene palettes, subtitles and a
working transport.
