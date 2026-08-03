#!/usr/bin/env bash
set -euo pipefail

SECONDS_TO_RUN="${1:-25}"
MAX_ERROR="${2:-8}"
BUILD="${BUILD:-build}"
BIOS_ZIP="${BIOS_ZIP:-$HOME/Library/Application Support/RetroArch/system/neogeo.zip}"
BIOS_ROM="${BIOS_ROM:-uni-bios_2_3.rom}"
BIOS_OPTION="${BIOS_OPTION:-unibios23}"
PREVIEW="${PREVIEW:-$BUILD/preview-spike.mkv}"

if ! command -v mame >/dev/null; then
    echo "mame not found on PATH" >&2
    exit 1
fi
for required in "$BUILD/aesmovie.zip" "$BUILD/mame-hash/neogeo.xml" "$PREVIEW"; do
    if [[ ! -f "$required" ]]; then
        echo "missing $required; bake and build first" >&2
        exit 1
    fi
done
if [[ ! -f "$BIOS_ZIP" ]]; then
    echo "BIOS archive not found: $BIOS_ZIP" >&2
    exit 1
fi

WORK="$(mktemp -d -t aesmovie-mame-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/roms" "$WORK/hash" "$WORK/snap" "$WORK/bios"

unzip -o -q -j "$BIOS_ZIP" "$BIOS_ROM" "000-lo.lo" -d "$WORK/bios"
( cd "$WORK/bios" && zip -q -X "$WORK/roms/aes.zip" "$BIOS_ROM" "000-lo.lo" )
cp -f "$BUILD/aesmovie.zip" "$WORK/roms/"
cp -f "$BUILD/mame-hash/neogeo.xml" "$WORK/hash/"

mame aes -bios "$BIOS_OPTION" -cart aesmovie \
    -rompath "$WORK/roms" -hashpath "$WORK/hash" -snapshot_directory "$WORK/snap" \
    -cfg_directory "$WORK/cfg" -nvram_directory "$WORK/nvram" -inipath "$WORK" \
    -video none -sound none -seconds_to_run "$SECONDS_TO_RUN" \
    -nothrottle -skip_gameinfo >/dev/null 2>&1

SHOT="$(find "$WORK/snap" -name '*.png' | head -1)"
if [[ -z "$SHOT" ]]; then
    echo "MAME produced no snapshot" >&2
    exit 1
fi

uv --project tools run python tools/scripts/verify_capture.py \
    --capture "$SHOT" --preview "$PREVIEW" \
    --overscan 0 --max-mean-error "$MAX_ERROR"
