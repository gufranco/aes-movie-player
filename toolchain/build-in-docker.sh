#!/bin/bash
set -euo pipefail

if [[ "$(uname)" != "Linux" ]]; then
    if ! command -v docker >/dev/null; then
        echo "Docker required on non-Linux hosts." >&2
        exit 1
    fi
    exec docker run --rm --platform linux/amd64 \
        -v "$PWD:/work" -w /work ubuntu:24.04 bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        retry() { local n=0; until "$@"; do n=$((n+1)); [ "$n" -ge 5 ] && return 1; echo "retry $n/5: $*" >&2; sleep 5; done; }
        retry apt-get update -q >/dev/null
        retry apt-get install -y --no-install-recommends \
          software-properties-common ca-certificates make pkg-config rsync zip \
          nodejs npm binutils python3 >/dev/null
        retry add-apt-repository -y ppa:dciabrin/ngdevkit >/dev/null
        retry apt-get update -q >/dev/null
        retry apt-get install -y --no-install-recommends ngdevkit ngdevkit-gngeo >/dev/null
        retry npm install -g --silent neosdconv@0.4.0 >/dev/null 2>&1
        bash toolchain/build-in-docker.sh
    '
fi

BUILD=build
ROM="$BUILD/rom"
BAKED="$BUILD/baked"
GENERATED="$BUILD/generated"

for required in "$BAKED/c1.bin" "$BAKED/c2.bin" "$BAKED/fix.s1" "$GENERATED/movie_data.S" "$GENERATED/movie_data.h"; do
    if [[ ! -f "$required" ]]; then
        echo "missing bake artifact: $required" >&2
        exit 1
    fi
done

mkdir -p "$ROM"

CFLAGS=(
    $(pkg-config --cflags ngdevkit)
    -Isrc
    -I"$GENERATED"
    -std=c99 -fomit-frame-pointer -O2 -g
    -Wall -Wextra -Werror
)

for unit in main menu; do
    echo "CC src/$unit.c"
    m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c "src/$unit.c" -o "$BUILD/$unit.o"
done

echo "AS $GENERATED/movie_data.S"
m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c "$GENERATED/movie_data.S" -o "$BUILD/movie_data.o"

echo "LD $BUILD/rom.elf"
m68k-neogeo-elf-gcc -o "$BUILD/rom.elf" "$BUILD/main.o" "$BUILD/menu.o" "$BUILD/movie_data.o" \
    -Wl,-Map="$BUILD/rom.map" $(pkg-config --libs ngdevkit)

echo "[ram] section sizes:"
m68k-neogeo-elf-size "$BUILD/rom.elf" || true

FIXED_ROM_BYTES=1048576
m68k-neogeo-elf-objcopy -O binary -S -R .text2 --gap-fill 0xff \
    "$BUILD/rom.elf" "$ROM/p1.raw"
RAW_SIZE=$(stat -c %s "$ROM/p1.raw")
STREAM_SIZE=$(stat -c %s "$BAKED/stream.bin")
STREAM_BANKS=$((STREAM_SIZE / FIXED_ROM_BYTES))
echo "[prom] code and tables $RAW_SIZE bytes of $FIXED_ROM_BYTES fixed"
echo "[prom] stream $STREAM_SIZE bytes in $STREAM_BANKS switchable bank(s)"
if [[ "$RAW_SIZE" -gt "$FIXED_ROM_BYTES" ]]; then
    echo "P-ROM overflow: $RAW_SIZE bytes exceeds the $FIXED_ROM_BYTES byte fixed region" >&2
    exit 1
fi
if [[ $((STREAM_SIZE % FIXED_ROM_BYTES)) -ne 0 ]]; then
    echo "stream is not a whole number of banks: $STREAM_SIZE bytes" >&2
    exit 1
fi
cp "$ROM/p1.raw" "$ROM/p1.p1"
truncate -s "$FIXED_ROM_BYTES" "$ROM/p1.p1"
cat "$BAKED/stream.bin" >> "$ROM/p1.p1"
dd if="$ROM/p1.p1" of="$ROM/p1.p1" conv=notrunc,swab status=none

cp /usr/share/ngdevkit/nullsound_driver.ihx "$ROM/m1.ihx"
z80-neogeo-ihx-sdobjcopy -I ihex -O binary "$ROM/m1.ihx" "$ROM/m1.m1" --pad-to 131072

cp "$BAKED/fix.s1" "$ROM/s1.s1"
: > "$ROM/v11.v1"
truncate -s 524288 "$ROM/v11.v1"

cp "$BAKED/c1.bin" "$ROM/c1.c1"
cp "$BAKED/c2.bin" "$ROM/c2.c2"
rm -f "$ROM/p1.raw" "$ROM/m1.ihx"

echo "[rom] sizes:"
ls -la "$ROM"

neosdconv -i "$ROM" -o "$BUILD/aesmovie.neo" \
    -n "AES Movie Player" -g Other -y 2026 -m aesmovie '-#' 9999 -s 1

ls -la "$BUILD/aesmovie.neo"
echo "DONE"
