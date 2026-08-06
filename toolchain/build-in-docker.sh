#!/bin/bash
set -euo pipefail

if ! command -v m68k-neogeo-elf-gcc >/dev/null; then
    if ! command -v docker >/dev/null; then
        echo "No m68k-neogeo-elf toolchain and no Docker to supply one." >&2
        exit 1
    fi
    exec docker run --rm --platform linux/amd64 \
        -e "BUILD=${BUILD:-build}" \
        -v "$PWD:/work" -w /work ubuntu:24.04 bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        retry() { local n=0; until "$@"; do n=$((n+1)); [ "$n" -ge 5 ] && return 1; echo "retry $n/5: $*" >&2; sleep 5; done; }
        retry apt-get update -q >/dev/null
        retry apt-get install -y --no-install-recommends \
          software-properties-common ca-certificates make pkg-config rsync zip \
          binutils python3 >/dev/null
        retry add-apt-repository -y ppa:dciabrin/ngdevkit >/dev/null
        retry apt-get update -q >/dev/null
        retry apt-get install -y --no-install-recommends ngdevkit ngdevkit-gngeo >/dev/null
        bash toolchain/build-in-docker.sh
    '
fi

retry_build() {
    local attempt=0
    until "$@"; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 4 ]; then
            echo "giving up after $attempt attempts: $*" >&2
            return 1
        fi
        echo "retry $attempt/4 after a toolchain failure: $*" >&2
        sleep 2
    done
}

file_size() {
    wc -c < "$1" | tr -d '[:space:]'
}

set_file_size() {
    if command -v gtruncate >/dev/null; then
        gtruncate -s "$2" "$1"
    else
        command truncate -s "$2" "$1"
    fi
}

BUILD="${BUILD:-build}"
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

NGDEVKIT_SHARE="${NGDEVKIT_SHARE:-$(pkg-config --variable=prefix ngdevkit)/share/ngdevkit}"

read -ra NGDEVKIT_CFLAGS <<< "$(pkg-config --cflags ngdevkit)"
read -ra NGDEVKIT_LIBS <<< "$(pkg-config --libs ngdevkit)"

CFLAGS=(
    "${NGDEVKIT_CFLAGS[@]}"
    -Isrc
    -I"$GENERATED"
    -Isrc/fmv -Isrc/player -I"$BAKED"
    -std=c99 -fomit-frame-pointer -O2 -g
    -Wall -Wextra -Werror
)

for unit in fmv/fmv fmv/fmv_audio fmv/timeline player/main player/menu; do
    name="$(basename "$unit")"
    echo "CC src/$unit.c"
    retry_build m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c "src/$unit.c" -o "$BUILD/$name.o"
done
echo "CC $GENERATED/movie_data_value.c"
retry_build m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c "$GENERATED/movie_data_value.c" \
    -o "$BUILD/movie_data_value.o"

echo "CHECK VRAM write spacing"
python3 tools/scripts/check_vram_timing.py "$BUILD/main.o" "$BUILD/menu.o" \
    "$BUILD/fmv.o" "$BUILD/timeline.o"

echo "AS $GENERATED/movie_data.S"
retry_build m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c "$GENERATED/movie_data.S" -o "$BUILD/movie_data.o"

FIXED_ROM_BYTES=1048576
BANK_WINDOW=2097152
BANK_LIMIT=8
STREAM_FIRST_BANK=0
STREAM_SIZE=$(file_size "$BAKED/stream.bin")
STREAM_BANKS=$((STREAM_SIZE / FIXED_ROM_BYTES))
if [[ $((STREAM_SIZE % FIXED_ROM_BYTES)) -ne 0 ]]; then
    echo "stream is not a whole number of banks: $STREAM_SIZE bytes" >&2
    exit 1
fi
if [[ $((STREAM_FIRST_BANK + STREAM_BANKS)) -gt "$BANK_LIMIT" ]]; then
    echo "stream ends past bank $BANK_LIMIT, which the three-bit latch cannot reach" >&2
    exit 1
fi

COMMON_OBJECTS=(
    "$BUILD/main.o" "$BUILD/menu.o" "$BUILD/fmv.o" "$BUILD/fmv_audio.o"
    "$BUILD/timeline.o" "$BUILD/movie_data_value.o" "$BUILD/movie_data.o"
)
BANK_IMAGES=()

for ((bank = 0; bank < STREAM_BANKS; bank++)); do
    stub="$GENERATED/fmv_stream__bank$bank.S"
    object="$BUILD/fmv_stream__bank$bank.o"
    elf="$BUILD/rom-bank$bank.elf"
    image="$BUILD/p2-bank$bank.bin"

    echo "AS $stub"
    retry_build m68k-neogeo-elf-gcc "${CFLAGS[@]}" -c "$stub" -o "$object"
    m68k-neogeo-elf-objcopy -R .text -R .data -R .bss "$object"
    echo "LD $elf"
    retry_build m68k-neogeo-elf-gcc -o "$elf" "${COMMON_OBJECTS[@]}" "$object" \
        -Wl,--defsym="fmv_stream_base=$((STREAM_FIRST_BANK * FIXED_ROM_BYTES))" \
        -Wl,-Map="$BUILD/rom-bank$bank.map" "${NGDEVKIT_LIBS[@]}"

    placed=$(m68k-neogeo-elf-nm "$elf" | awk -v want="fmv_stream_bank$bank" '$3 == want {print $1}')
    if [[ "$placed" != "00200000" ]]; then
        echo "stream bank $bank sits at 0x${placed:-?}, not at the start of the switchable window" >&2
        echo "something else was linked into .text2 ahead of it" >&2
        exit 1
    fi
    m68k-neogeo-elf-objcopy -O binary -j .text2 --gap-fill 0x00 \
        --pad-to $((BANK_WINDOW + FIXED_ROM_BYTES)) "$elf" "$image"
    if [[ "$(file_size "$image")" -ne "$FIXED_ROM_BYTES" ]]; then
        echo "switchable bank $bank came out $(file_size "$image") bytes, not $FIXED_ROM_BYTES" >&2
        exit 1
    fi
    BANK_IMAGES+=("$image")
done

cp -f "$BUILD/rom-bank0.elf" "$BUILD/rom.elf"
cp -f "$BUILD/rom-bank0.map" "$BUILD/rom.map"

echo "[ram] section sizes:"
m68k-neogeo-elf-size -A "$BUILD/rom.elf" | awk '$1 !~ /^\.debug/' || true

m68k-neogeo-elf-objcopy -O binary -S -R .text2 --gap-fill 0xff \
    "$BUILD/rom.elf" "$ROM/p1.raw"
RAW_SIZE=$(file_size "$ROM/p1.raw")
echo "[prom] code and tables $RAW_SIZE bytes of $FIXED_ROM_BYTES fixed"
echo "[prom] stream $STREAM_SIZE bytes in $STREAM_BANKS switchable bank(s) from bank $STREAM_FIRST_BANK"
if [[ "$RAW_SIZE" -gt "$FIXED_ROM_BYTES" ]]; then
    echo "P-ROM overflow: $RAW_SIZE bytes exceeds the $FIXED_ROM_BYTES byte fixed region" >&2
    exit 1
fi
cp -f "$ROM/p1.raw" "$ROM/p1.p1"
set_file_size "$ROM/p1.p1" "$FIXED_ROM_BYTES"
cat "${BANK_IMAGES[@]}" >> "$ROM/p1.p1"
dd if="$ROM/p1.p1" of="$ROM/p1.p1" conv=notrunc,swab status=none

if [[ -f "$GENERATED/audio_params.s" ]]; then
    echo "AS src/fmv/sound.s"
    z80-neogeo-ihx-sdasz80 -o "$BUILD/sound.rel" src/fmv/sound.s
    z80-neogeo-ihx-sdldz80 -n -i "$BUILD/sound.ihx" "$BUILD/sound.rel"
    z80-neogeo-ihx-sdobjcopy -I ihex -O binary "$BUILD/sound.ihx" "$ROM/m1.m1" --pad-to 131072
else
    cp "$NGDEVKIT_SHARE/nullsound_driver.ihx" "$ROM/m1.ihx"
    z80-neogeo-ihx-sdobjcopy -I ihex -O binary "$ROM/m1.ihx" "$ROM/m1.m1" --pad-to 131072
    rm -f "$ROM/m1.ihx"
fi

cp "$BAKED/fix.s1" "$ROM/s1.s1"
: > "$ROM/v11.v1"
set_file_size "$ROM/v11.v1" 524288

if [[ -f "$BAKED/v2.bin" ]]; then
    cp "$BAKED/v2.bin" "$ROM/v21.v2"
    echo "[audio] ADPCM-B voice ROM $(file_size "$ROM/v21.v2") bytes"
else
    rm -f "$ROM/v21.v2"
fi

cp "$BAKED/c1.bin" "$ROM/c1.c1"
cp "$BAKED/c2.bin" "$ROM/c2.c2"
rm -f "$ROM/p1.raw"

echo "[rom] sizes:"
ls -la "$ROM"

python3 tools/aesmovie/neofile.py --rom-dir "$ROM" --output "$BUILD/aesmovie.neo"
python3 tools/aesmovie/mamecart.py --rom-dir "$ROM" --output "$BUILD/aesmovie.zip"

ls -la "$BUILD/aesmovie.neo"
echo "DONE"
