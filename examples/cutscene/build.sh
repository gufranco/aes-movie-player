#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="${BUNDLE:-$PWD/build/bundle}"
WORK="${WORK:-$PWD/build/example}"
EXAMPLES_REF="${EXAMPLES_REF:-60f1bd113471ade1a1850e0dca945cffeef38231}"
EXAMPLES_URL="${EXAMPLES_URL:-https://github.com/dciabrin/ngdevkit-examples.git}"
FMV_AUDIO="${FMV_AUDIO:-no}"
AUDIO_FLAG=""
if [[ "$FMV_AUDIO" == "yes" ]]; then
    AUDIO_FLAG="--audio"
fi

if [[ ! -d "$BUNDLE/movie" ]]; then
    echo "no bundle at $BUNDLE; bake one with --bundle first" >&2
    exit 1
fi

fetch_stock_project() {
    local upstream="$1"

    if [[ ! -d "$upstream/.git" ]]; then
        echo "[fetch] a stock ngdevkit project"
        git clone -q "$EXAMPLES_URL" "$upstream"
        git -C "$upstream" checkout -q "$EXAMPLES_REF"
    fi
    if [[ ! -f "$upstream/config.mk" ]]; then
        echo "[configure] the stock project"
        if ! ( cd "$upstream" && autoreconf -i >/dev/null 2>&1 && ./configure >config.log 2>&1 ); then
            echo "configuring the stock project failed; see $upstream/config.log" >&2
            exit 1
        fi
    fi
}

drop_demo_assets_this_example_does_not_use() {
    local project="$1"

    rm -rf "$project/setup" "$project/assets"
    mkdir -p "$project/assets"
}

mkdir -p "$WORK"
UPSTREAM="$WORK/ngdevkit-examples"
fetch_stock_project "$UPSTREAM"

PROJECT="$WORK/cutscene"
rm -rf "$PROJECT"
cp -Rf "$UPSTREAM/00-template" "$PROJECT"
cp -f "$UPSTREAM/config.mk" "$PROJECT/config.mk"
drop_demo_assets_this_example_does_not_use "$PROJECT"

cp -f "$HERE/main.c" "$PROJECT/main.c"
cp -Rf "$BUNDLE" "$PROJECT/fmv"

echo "[integrate] the edits the bundle's guide asks for"
uv --project "$HERE/../../tools" run python -m aesmovie.integrate "$PROJECT" $AUDIO_FLAG

echo "[build] the cartridge"
# shellcheck disable=SC2016
make -C "$PROJECT" CART_TARGETS='$(CART_ZIP) $(HASH_MAME)' cart

echo "[done] $PROJECT/build/rom"
command ls -la "$PROJECT/build/rom"
