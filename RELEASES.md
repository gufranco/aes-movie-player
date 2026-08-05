# Releases

Generated from commit subjects by python-semantic-release, one entry per
version. What the project tried and rejected is in
[CHANGELOG.md](CHANGELOG.md); this file is only the version history.

<!-- version list -->

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
