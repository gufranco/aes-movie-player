"""Exercise the library as compiled C, against a stub of the hardware.

`src/fmv/fmv.c` is the half of the player that touches registers, so it
cannot run on the host without something standing in for them. The stub
in `hwstub/hw.h` is that stand-in, and it is deliberately not a faithful
mirror: the fix-source, palette-bank and bank latches are exposed only
through the functions that write them, with no read path at all. That is
what the board offers, and modelling it any other way would let a
save-by-reading defect pass, which is exactly the defect these tests
exist to keep out.

What runs here is the translation unit that ships, built by the host
compiler and called through ctypes, rather than a Python copy of it.

The blobs these tests hand it are packed in the host's byte order rather
than the cartridge's. Byte order is a property of the target, and what is
under test is the arithmetic that walks those blobs: which epoch covers a
frame, which bank an offset falls in, which slot a run starts at. The
cartridge's own big-endian packing is checked where it belongs, against
the emulator transcriptions.
"""

from __future__ import annotations

import ctypes
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY_DIR = ROOT / "src" / "fmv"
STUB_DIR = Path(__file__).resolve().parent / "hwstub"

GRID_COLS = 20
GRID_ROWS = 14
PALETTE_WORDS = 16
EPOCH_PALETTES = 4
EPOCH_SLICE = 8
PALETTE_BASE = 16
FIRST_SPRITE = 1
FRAMES = 3

VRAM_SCB3 = 0x8200
SCB1_WORDS_PER_SPRITE = 64

FMV_FIX_CART = 0
FMV_FIX_BOARD = 1
FMV_FINISHED = 0
FMV_SKIPPED = 1
FMV_PAD_A = 0x10
FMV_START = 0x01
SOUND_PLAY = 0x50
SOUND_STOP = 0x60

SKIP_FN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)


class Options(ctypes.Structure):
    _fields_ = [
        ("first_sprite", ctypes.c_uint16),
        ("top_line", ctypes.c_uint16),
        ("left_pixel", ctypes.c_uint16),
        ("lspc_mode", ctypes.c_uint16),
        ("fix_source", ctypes.c_uint8),
        ("palette_bank", ctypes.c_uint8),
        ("prom_bank", ctypes.c_uint8),
        ("skip_pad", ctypes.c_uint8),
        ("skip_start", ctypes.c_uint8),
        ("audio", ctypes.c_uint8),
        ("skip", SKIP_FN),
        ("skip_user", ctypes.c_void_p),
    ]


class Movie(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_void_p),
        ("keyframes", ctypes.c_void_p),
        ("palettes", ctypes.c_void_p),
        ("epochs", ctypes.c_void_p),
        ("subtitles", ctypes.c_void_p),
        ("stream_base", ctypes.c_uint32),
        ("frames", ctypes.c_uint32),
        ("keyframe_count", ctypes.c_uint32),
        ("fps_num", ctypes.c_uint32),
        ("fps_den", ctypes.c_uint32),
        ("audio_page_num", ctypes.c_uint32),
        ("audio_page_den", ctypes.c_uint32),
        ("epoch_count", ctypes.c_uint16),
        ("epoch_palettes", ctypes.c_uint16),
        ("epoch_slice", ctypes.c_uint16),
        ("palette_base", ctypes.c_uint16),
        ("first_sprite", ctypes.c_uint16),
        ("grid_cols", ctypes.c_uint16),
        ("grid_rows", ctypes.c_uint16),
        ("max_updates", ctypes.c_uint16),
        ("subtitle_count", ctypes.c_uint16),
        ("subtitle_columns", ctypes.c_uint16),
        ("subtitle_lines", ctypes.c_uint16),
    ]


PLAYER_BYTES = 256


def _stage(root: Path) -> Path:
    """Copy the library beside the stub, because `#include "hw.h"` is quoted.

    A quoted include resolves against the directory of the file doing the
    including before it looks at anything on the search path, so the real
    header would win however the flags are ordered. Standing the sources
    next to the stub is also how a developer holding an emitted folder
    sees them: one directory, one header of each name.
    """
    staged = root / "fmv"
    staged.mkdir()
    for source in sorted(LIBRARY_DIR.glob("*.[ch]")):
        shutil.copy2(source, staged / source.name)
    shutil.copy2(STUB_DIR / "hw.h", staged / "hw.h")
    shutil.copy2(STUB_DIR / "probe.c", staged / "probe.c")
    return staged


def _build(tmp_path_factory, *, audio: bool):
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None:
        pytest.skip("no host C compiler")
    name = "audio" if audio else "silent"
    root = tmp_path_factory.mktemp(f"fmv-{name}")
    staged = _stage(root)
    library = root / f"libfmv-{name}.so"
    sources = [staged / "fmv.c", staged / "timeline.c", staged / "probe.c"]
    if audio:
        sources.append(staged / "fmv_audio.c")
    command = [
        compiler,
        "-std=c99",
        "-O1",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-shared",
        "-fPIC",
        f"-I{staged}",
    ]
    if not audio:
        command.append("-DFMV_NO_AUDIO")
    command += [str(path) for path in sources] + ["-o", str(library)]
    subprocess.run(command, check=True)

    loaded = ctypes.CDLL(str(library))
    loaded.fmv_defaults.restype = Options
    loaded.fmv_position.restype = ctypes.c_uint32
    loaded.fmv_ended.restype = ctypes.c_int
    loaded.fmv_last_updates.restype = ctypes.c_uint16
    loaded.fmv_play.restype = ctypes.c_int
    for name in (
        "fmv_test_lspc_mode",
        "fmv_test_prom_bank",
        "fmv_test_watchdog_kicks",
        "fmv_test_vblank_waits",
        "fmv_test_vram",
        "fmv_test_palram",
        "fmv_test_player_stream_bank",
        "fmv_test_player_updates",
        "fmv_test_player_epoch",
        "fmv_test_player_sprite_offset",
    ):
        getattr(loaded, name).restype = ctypes.c_uint16
    for name in (
        "fmv_test_fix_source",
        "fmv_test_palette_bank",
        "fmv_test_player_open",
        "fmv_test_last_sound_command",
    ):
        getattr(loaded, name).restype = ctypes.c_uint8
    loaded.fmv_test_player_frame.restype = ctypes.c_uint32
    for name in ("fmv_test_sizeof_options", "fmv_test_sizeof_movie", "fmv_test_sizeof_player"):
        getattr(loaded, name).restype = ctypes.c_size_t
    return loaded


@pytest.fixture(scope="session")
def fmv(tmp_path_factory):
    return _build(tmp_path_factory, audio=True)


@pytest.fixture(scope="session")
def silent_fmv(tmp_path_factory):
    return _build(tmp_path_factory, audio=False)


def _keyframe_record() -> bytes:
    """One run covering the whole first column, so a frame writes tiles."""
    body = struct.pack("=H", 1)
    body += struct.pack("=HH", FIRST_SPRITE * SCB1_WORDS_PER_SPRITE, GRID_ROWS)
    for row in range(GRID_ROWS):
        body += struct.pack("=HH", 0x1000 + row, 0x0020)
    return body


@pytest.fixture
def movie(fmv):
    return _movie_for(fmv)


def _movie_for(library):
    library.fmv_test_reset()

    record = _keyframe_record()
    stream = bytearray()
    offsets = []
    for _ in range(FRAMES):
        offsets.append(len(stream))
        stream += record
    stream_buffer = (ctypes.c_uint8 * len(stream)).from_buffer_copy(bytes(stream))
    library.fmv_test_set_bank_window(stream_buffer)

    index = (ctypes.c_uint8 * (4 * FRAMES)).from_buffer_copy(
        b"".join(struct.pack("=I", value) for value in offsets)
    )
    keyframes = (ctypes.c_uint8 * 4).from_buffer_copy(struct.pack("=I", 0))
    epochs = (ctypes.c_uint8 * 4).from_buffer_copy(struct.pack("=I", 0))
    palettes = (ctypes.c_uint8 * (2 * EPOCH_PALETTES * PALETTE_WORDS))()
    for word in range(EPOCH_PALETTES * PALETTE_WORDS):
        struct.pack_into("=H", palettes, word * 2, 0x8000 | word)
    subtitles = (ctypes.c_uint8 * 4)()

    value = Movie(
        index=ctypes.cast(index, ctypes.c_void_p),
        keyframes=ctypes.cast(keyframes, ctypes.c_void_p),
        palettes=ctypes.cast(palettes, ctypes.c_void_p),
        epochs=ctypes.cast(epochs, ctypes.c_void_p),
        subtitles=ctypes.cast(subtitles, ctypes.c_void_p),
        stream_base=0,
        frames=FRAMES,
        keyframe_count=1,
        fps_num=15625,
        fps_den=264,
        audio_page_num=1,
        audio_page_den=1000,
        epoch_count=1,
        epoch_palettes=EPOCH_PALETTES,
        epoch_slice=EPOCH_SLICE,
        palette_base=PALETTE_BASE,
        first_sprite=FIRST_SPRITE,
        grid_cols=GRID_COLS,
        grid_rows=GRID_ROWS,
        max_updates=GRID_ROWS,
        subtitle_count=0,
        subtitle_columns=40,
        subtitle_lines=2,
    )
    value._keepalive = (index, keyframes, epochs, palettes, subtitles, stream_buffer)
    return value


def _player() -> ctypes.Array:
    return (ctypes.c_uint8 * PLAYER_BYTES)()


class TestLayoutAgreement:
    def test_the_options_mirror_matches_the_compiled_struct(self, fmv):
        assert ctypes.sizeof(Options) == fmv.fmv_test_sizeof_options()

    def test_the_movie_mirror_matches_the_compiled_struct(self, fmv):
        assert ctypes.sizeof(Movie) == fmv.fmv_test_sizeof_movie()

    def test_the_skip_hook_sits_where_the_compiled_struct_puts_it(self, fmv):
        assert Options.skip.offset == fmv.fmv_test_offsetof_options_skip()

    def test_the_player_fits_the_buffer_the_tests_hand_it(self, fmv):
        assert fmv.fmv_test_sizeof_player() <= PLAYER_BYTES


class TestDefaults:
    def test_the_grid_starts_at_the_first_drawn_sprite(self, fmv):
        assert fmv.fmv_defaults().first_sprite == 1

    def test_the_picture_starts_at_the_origin(self, fmv):
        options = fmv.fmv_defaults()

        assert (options.top_line, options.left_pixel) == (0, 0)

    def test_the_machine_it_hands_back_is_a_plain_cartridge(self, fmv):
        options = fmv.fmv_defaults()

        assert options.lspc_mode == 0
        assert options.fix_source == FMV_FIX_CART
        assert options.palette_bank == 0
        assert options.prom_bank == 0

    def test_a_button_and_start_both_skip_by_default(self, fmv):
        options = fmv.fmv_defaults()

        assert options.skip_pad == FMV_PAD_A
        assert options.skip_start == 1

    def test_no_skip_predicate_is_installed(self, fmv):
        assert not fmv.fmv_defaults().skip


class TestOpening:
    def test_it_takes_the_fix_rom_and_palette_bank_it_needs(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        assert fmv.fmv_test_fix_source() == FMV_FIX_CART
        assert fmv.fmv_test_palette_bank() == 0

    def test_it_disables_auto_animation_while_it_owns_the_screen(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        assert fmv.fmv_test_lspc_mode() == 0x0008

    def test_it_lays_out_one_sprite_per_column(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        for column in range(GRID_COLS):
            assert fmv.fmv_test_vram(VRAM_SCB3 + FIRST_SPRITE + column) != 0, column

    def test_a_caller_that_owns_the_low_sprites_gets_the_grid_moved_up(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.first_sprite = 8
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        assert fmv.fmv_test_vram(VRAM_SCB3 + 8) != 0
        assert fmv.fmv_test_vram(VRAM_SCB3 + FIRST_SPRITE) == 0

    def test_moving_the_grid_offsets_every_stream_address(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.first_sprite = 8
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        expected = (8 - FIRST_SPRITE) * SCB1_WORDS_PER_SPRITE

        assert fmv.fmv_test_player_sprite_offset(player) == expected

    def test_it_uploads_the_first_epoch_into_the_bank_it_was_given(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        assert fmv.fmv_test_palram(PALETTE_BASE * PALETTE_WORDS) == 0x8000

    def test_it_leaves_the_callers_own_palettes_untouched(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        for word in range(PALETTE_BASE * PALETTE_WORDS):
            assert fmv.fmv_test_palram(word) == 0, word

    def test_it_kicks_the_watchdog_while_it_sets_up(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()

        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        assert fmv.fmv_test_watchdog_kicks() >= 2


class TestGivingTheMachineBack:
    def _played(self, fmv, movie, options):
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))
        fmv.fmv_start(player)
        fmv.fmv_close(player)
        return player

    def test_it_restores_the_lspc_mode_the_caller_declared(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.lspc_mode = 0x0400

        self._played(fmv, movie, options)

        assert fmv.fmv_test_lspc_mode() == 0x0400

    def test_it_restores_the_board_fix_rom_when_that_is_what_the_caller_uses(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.fix_source = FMV_FIX_BOARD

        self._played(fmv, movie, options)

        assert fmv.fmv_test_fix_source() == FMV_FIX_BOARD

    def test_it_restores_the_palette_bank_the_caller_declared(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.palette_bank = 1

        self._played(fmv, movie, options)

        assert fmv.fmv_test_palette_bank() == 1

    def test_it_restores_the_program_bank_the_caller_declared(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.prom_bank = 3

        self._played(fmv, movie, options)

        assert fmv.fmv_test_prom_bank() == 3

    def test_it_disables_the_sprites_it_borrowed(self, fmv, movie):
        options = fmv.fmv_defaults()

        self._played(fmv, movie, options)

        for column in range(GRID_COLS):
            assert fmv.fmv_test_vram(VRAM_SCB3 + FIRST_SPRITE + column) == 0, column

    def test_it_blanks_the_palettes_it_borrowed(self, fmv, movie):
        options = fmv.fmv_defaults()

        self._played(fmv, movie, options)

        for word in range(2 * EPOCH_PALETTES * PALETTE_WORDS):
            assert fmv.fmv_test_palram(PALETTE_BASE * PALETTE_WORDS + word) == 0, word

    def test_closing_twice_is_harmless(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = self._played(fmv, movie, options)
        options.prom_bank = 7

        fmv.fmv_close(player)

        assert fmv.fmv_test_prom_bank() == 0

    def test_a_closed_player_says_so(self, fmv, movie):
        options = fmv.fmv_defaults()

        player = self._played(fmv, movie, options)

        assert fmv.fmv_test_player_open(player) == 0


class TestAdvancing:
    def test_the_first_frame_is_drawn_by_start(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        fmv.fmv_start(player)

        assert fmv.fmv_position(player) == 1

    def test_a_tick_advances_one_frame(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))
        fmv.fmv_start(player)

        fmv.fmv_tick(player)

        assert fmv.fmv_position(player) == 2

    def test_a_frame_reports_what_it_wrote(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        fmv.fmv_start(player)

        assert fmv.fmv_last_updates(player) == GRID_ROWS

    def test_it_ends_after_the_last_frame(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))
        fmv.fmv_start(player)

        for _ in range(FRAMES):
            fmv.fmv_tick(player)

        assert fmv.fmv_ended(player) == 1

    def test_a_tick_past_the_end_does_nothing(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))
        fmv.fmv_start(player)
        for _ in range(FRAMES):
            fmv.fmv_tick(player)
        settled = fmv.fmv_position(player)

        fmv.fmv_tick(player)

        assert fmv.fmv_position(player) == settled

    def test_a_seek_lands_on_the_keyframe_at_or_before_the_target(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))
        fmv.fmv_start(player)

        fmv.fmv_seek(player, 2)

        assert fmv.fmv_position(player) == 1

    def test_the_stream_bank_follows_the_base_the_linker_gave_it(self, fmv, movie):
        movie.stream_base = 3 * 0x100000
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        fmv.fmv_start(player)

        assert fmv.fmv_test_player_stream_bank(player) == 3


class TestSkipping:
    def test_a_movie_left_alone_runs_to_the_end(self, fmv, movie):
        options = fmv.fmv_defaults()
        fmv.fmv_test_set_pad(0xFF, 0xFF)

        assert fmv.fmv_play(ctypes.byref(movie), ctypes.byref(options)) == FMV_FINISHED

    def test_a_masked_button_ends_it_early(self, fmv, movie):
        options = fmv.fmv_defaults()
        fmv.fmv_test_set_pad(0xFF & ~FMV_PAD_A, 0xFF)

        assert fmv.fmv_play(ctypes.byref(movie), ctypes.byref(options)) == FMV_SKIPPED

    def test_start_ends_it_early(self, fmv, movie):
        options = fmv.fmv_defaults()
        fmv.fmv_test_set_pad(0xFF, 0xFF & ~FMV_START)

        assert fmv.fmv_play(ctypes.byref(movie), ctypes.byref(options)) == FMV_SKIPPED

    def test_a_caller_predicate_replaces_the_pad_entirely(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.skip = SKIP_FN(lambda _user: 1)
        fmv.fmv_test_set_pad(0xFF, 0xFF)

        assert fmv.fmv_play(ctypes.byref(movie), ctypes.byref(options)) == FMV_SKIPPED

    def test_a_predicate_that_never_fires_lets_the_movie_finish(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.skip = SKIP_FN(lambda _user: 0)
        fmv.fmv_test_set_pad(0x00, 0x00)

        assert fmv.fmv_play(ctypes.byref(movie), ctypes.byref(options)) == FMV_FINISHED

    def test_a_skipped_movie_still_gives_the_machine_back(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.palette_bank = 1
        options.prom_bank = 2
        fmv.fmv_test_set_pad(0xFF & ~FMV_PAD_A, 0xFF)

        fmv.fmv_play(ctypes.byref(movie), ctypes.byref(options))

        assert fmv.fmv_test_palette_bank() == 1
        assert fmv.fmv_test_prom_bank() == 2


class TestTheAudioSwitch:
    def test_a_build_with_audio_cues_the_soundtrack(self, fmv, movie):
        options = fmv.fmv_defaults()
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        fmv.fmv_start(player)

        assert fmv.fmv_test_last_sound_command() == SOUND_PLAY

    def test_a_caller_that_asks_for_silence_sends_nothing(self, fmv, movie):
        options = fmv.fmv_defaults()
        options.audio = 0
        player = _player()
        fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        fmv.fmv_start(player)

        assert fmv.fmv_test_last_sound_command() == 0

    def test_a_video_only_build_sends_nothing_at_all(self, silent_fmv):
        movie = _movie_for(silent_fmv)
        options = silent_fmv.fmv_defaults()
        player = _player()
        silent_fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        silent_fmv.fmv_start(player)

        assert silent_fmv.fmv_test_last_sound_command() == 0

    def test_a_video_only_build_still_draws_the_movie(self, silent_fmv):
        movie = _movie_for(silent_fmv)
        options = silent_fmv.fmv_defaults()
        player = _player()
        silent_fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))

        silent_fmv.fmv_start(player)

        assert silent_fmv.fmv_last_updates(player) == GRID_ROWS

    def test_a_video_only_build_still_gives_the_machine_back(self, silent_fmv):
        movie = _movie_for(silent_fmv)
        options = silent_fmv.fmv_defaults()
        options.prom_bank = 4
        player = _player()
        silent_fmv.fmv_open(player, ctypes.byref(movie), ctypes.byref(options))
        silent_fmv.fmv_start(player)

        silent_fmv.fmv_close(player)

        assert silent_fmv.fmv_test_prom_bank() == 4
