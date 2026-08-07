#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
MOVIE="$HERE/../{movie_dir}"
ROM_DIR="${{1:-build/rom}}"
GAME="${{2:-ngdevkit}}"
OUTPUT="${{3:-$GAME}}"

if [[ ! -d "$ROM_DIR" ]]; then
    echo "usage: package.sh <rom-dir> [game-name] [output-base]" >&2
    exit 1
fi

STAGE="$(mktemp -d -t fmv-package-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT

require() {{
    if [[ ! -f "$1" ]]; then
        echo "missing $1" >&2
        exit 1
    fi
}}

require "$ROM_DIR/$GAME-p1.p1"
require "$ROM_DIR/$GAME-s1.s1"
require "$ROM_DIR/$GAME-m1.m1"
require "$ROM_DIR/$GAME-c1.c1"
require "$ROM_DIR/$GAME-c2.c2"

# The containers take one program ROM holding the fixed megabyte and every
# switchable bank after it. An ngdevkit project builds those as two files,
# so they are joined here. Leaving the second one out costs the movie its
# command stream, and the cartridge then plays a blank screen.
cat "$ROM_DIR/$GAME-p1.p1" > "$STAGE/p1.p1"
if [[ -f "$ROM_DIR/$GAME-p2.p2" ]]; then
    cat "$ROM_DIR/$GAME-p2.p2" >> "$STAGE/p1.p1"
fi

cp "$ROM_DIR/$GAME-s1.s1" "$STAGE/s1.s1"
cp "$ROM_DIR/$GAME-m1.m1" "$STAGE/m1.m1"
cp "$ROM_DIR/$GAME-c1.c1" "$STAGE/c1.c1"
cp "$ROM_DIR/$GAME-c2.c2" "$STAGE/c2.c2"

: > "$STAGE/v11.v1"
if command -v gtruncate >/dev/null; then
    gtruncate -s 524288 "$STAGE/v11.v1"
else
    truncate -s 524288 "$STAGE/v11.v1"
fi

if [[ -f "$MOVIE/v2.bin" ]]; then
    cp "$MOVIE/v2.bin" "$STAGE/v21.v2"
    echo "[audio] the movie's soundtrack goes in as the ADPCM-B ROM"
fi

python3 "$HERE/neofile.py" --rom-dir "$STAGE" --output "$OUTPUT.neo"
python3 "$HERE/mamecart.py" --rom-dir "$STAGE" --output "$OUTPUT.zip"
echo "[done] $OUTPUT.neo, $OUTPUT.zip and the software list beside it"
