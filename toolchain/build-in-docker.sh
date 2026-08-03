#!/bin/bash
set -euo pipefail

if [[ "$(uname)" != "Linux" ]]; then
    if ! command -v docker >/dev/null; then
        echo "Docker required on non-Linux hosts." >&2
        exit 1
    fi
    exec docker run --rm --platform linux/amd64 \
        -e "P_ROM_BYTES=${P_ROM_BYTES:-524288}" \
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

for required in "$BAKED/c1.bin" "$BAKED/c2.bin" "$GENERATED/movie_data.S" "$GENERATED/movie_data.h"; do
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

echo "CC src/main.c"
m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c src/main.c -o "$BUILD/main.o"

echo "AS $GENERATED/movie_data.S"
m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c "$GENERATED/movie_data.S" -o "$BUILD/movie_data.o"

echo "LD $BUILD/rom.elf"
m68k-neogeo-elf-gcc -o "$BUILD/rom.elf" "$BUILD/main.o" "$BUILD/movie_data.o" \
    -Wl,-Map="$BUILD/rom.map" $(pkg-config --libs ngdevkit)

echo "[ram] section sizes:"
m68k-neogeo-elf-size "$BUILD/rom.elf" || true

P_ROM_BYTES="${P_ROM_BYTES:-524288}"
m68k-neogeo-elf-objcopy -O binary -S -R .text2 --gap-fill 0xff \
    "$BUILD/rom.elf" "$ROM/p1.raw"
RAW_SIZE=$(stat -c %s "$ROM/p1.raw")
echo "[prom] payload $RAW_SIZE bytes of $P_ROM_BYTES"
if [[ "$RAW_SIZE" -gt "$P_ROM_BYTES" ]]; then
    echo "P-ROM overflow: $RAW_SIZE bytes exceeds the $P_ROM_BYTES byte window" >&2
    exit 1
fi
cp "$ROM/p1.raw" "$ROM/p1.p1"
truncate -s "$P_ROM_BYTES" "$ROM/p1.p1"
dd if="$ROM/p1.p1" of="$ROM/p1.p1" conv=notrunc,swab status=none

cp /usr/share/ngdevkit/nullsound_driver.ihx "$ROM/m1.ihx"
z80-neogeo-ihx-sdobjcopy -I ihex -O binary "$ROM/m1.ihx" "$ROM/m1.m1" --pad-to 131072

: > "$ROM/s1.s1"
truncate -s 131072 "$ROM/s1.s1"
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
