#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WORK="${WORK:-$PWD/build/example}"
PREVIEW="${PREVIEW:-$PWD/build/preview-spike.mkv}"
ROM_DIR="${ROM_DIR:-$WORK/cutscene/build/rom}"
BIOS_ZIP="${BIOS_ZIP:-$HOME/Library/Application Support/RetroArch/system/neogeo.zip}"
BIOS_ROM="${BIOS_ROM:-uni-bios_2_3.rom}"
BIOS_OPTION="${BIOS_OPTION:-unibios23}"
BOOT_ALLOWANCE="${BOOT_ALLOWANCE:-15}"
SETTLE_MARGIN="${SETTLE_MARGIN:-6}"
STILL_MARGIN="${STILL_MARGIN:-5}"

if ! command -v mame >/dev/null; then
    echo "mame not found on PATH" >&2
    exit 1
fi
for required in "$ROM_DIR/ngdevkit.zip" "$ROM_DIR/neogeo.xml" "$PREVIEW"; do
    if [[ ! -f "$required" ]]; then
        echo "missing $required; build the example first" >&2
        exit 1
    fi
done
if [[ ! -f "$BIOS_ZIP" ]]; then
    echo "BIOS archive not found: $BIOS_ZIP" >&2
    exit 1
fi

MOVIE_SECONDS="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$PREVIEW" \
    | command cut -d. -f1)"
if [[ -z "$MOVIE_SECONDS" ]]; then
    echo "could not read the length of $PREVIEW" >&2
    exit 1
fi
SETTLED_SECONDS=$((BOOT_ALLOWANCE + MOVIE_SECONDS + SETTLE_MARGIN))
STILL_SECONDS=$((SETTLED_SECONDS + STILL_MARGIN))
echo "[plan] the cutscene runs ${MOVIE_SECONDS}s, so the screen is read at ${SETTLED_SECONDS}s and ${STILL_SECONDS}s"

STAGE="$(mktemp -d -t cutscene-verify-XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/roms" "$STAGE/hash" "$STAGE/bios" "$STAGE/shots"

unzip -o -q -j "$BIOS_ZIP" "$BIOS_ROM" "000-lo.lo" -d "$STAGE/bios"
( cd "$STAGE/bios" && zip -q -X "$STAGE/roms/aes.zip" "$BIOS_ROM" "000-lo.lo" )
cp -f "$ROM_DIR/ngdevkit.zip" "$STAGE/roms/"
cp -f "$ROM_DIR/neogeo.xml" "$STAGE/hash/"

capture_at() {
    local seconds="$1"
    local target="$2"
    local snap="$STAGE/snap-$seconds"

    rm -rf "$snap"
    mkdir -p "$snap"
    mame aes -bios "$BIOS_OPTION" -cart ngdevkit \
        -rompath "$STAGE/roms" -hashpath "$STAGE/hash" -snapshot_directory "$snap" \
        -cfg_directory "$STAGE/cfg" -nvram_directory "$STAGE/nvram" -inipath "$STAGE" \
        -noreadconfig -video none -sound none -window -nomaximize \
        -seconds_to_run "$seconds" -nothrottle -skip_gameinfo >/dev/null 2>&1
    local shot
    shot="$(command find "$snap" -name '*.png' | head -1)"
    if [[ -z "$shot" ]]; then
        echo "MAME produced no snapshot at $seconds seconds" >&2
        exit 1
    fi
    cp -f "$shot" "$target"
}

echo "[run] the cutscene through to the caller's own screen"
capture_at "$SETTLED_SECONDS" "$STAGE/shots/settled.png"
capture_at "$STILL_SECONDS" "$STAGE/shots/still.png"

if ! cmp -s "$STAGE/shots/settled.png" "$STAGE/shots/still.png"; then
    echo "FAIL: the screen kept changing after the cutscene returned" >&2
    exit 1
fi
echo "the caller's screen is stable across $((STILL_SECONDS - SETTLED_SECONDS)) emulated seconds"

if uv --project "$ROOT/tools" run python "$ROOT/tools/scripts/verify_capture.py" \
        --capture "$STAGE/shots/settled.png" --preview "$PREVIEW" \
        --overscan 0 --max-mean-error 8 >/dev/null 2>&1; then
    echo "FAIL: the screen still matches a frame of the movie" >&2
    exit 1
fi
echo "nothing of the movie is left on the caller's screen"

echo "PASS"
