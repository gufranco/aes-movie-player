from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def check_vram_timing():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "check_vram_timing", SCRIPTS / "check_vram_timing.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def listing(*rows: str) -> str:
    header = [
        "sample.o:     file format elf32-m68k",
        "",
        "",
        "Disassembly of section .text:",
        "",
        "00000000 <sample>:",
    ]
    return "\n".join(header + list(rows)) + "\n"


def instruction(address: int, encoding: str, text: str) -> str:
    return f" {address:x}:\t{encoding} \t{text}"


def continuation(address: int, encoding: str) -> str:
    return f" {address:x}:\t{encoding} "


class TestPairsUnderTheDocumentedFloor:
    def test_it_flags_a_long_immediate_poke_followed_directly_by_a_register_poke(
        self, check_vram_timing
    ):
        source = listing(
            instruction(0x4D6, "23fc 74ba 1016", "movel #1958350870,3c0000 <x>"),
            continuation(0x4DC, "003c 0000"),
            instruction(0x4E0, "23c9 003c 0000", "movel %a1,3c0000 <x>"),
            instruction(0x4E6, "4e75", "rts"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert len(found) == 1
        assert found[0].gap == 12
        assert found[0].floor == check_vram_timing.MIN_CYCLES_DATA_TO_ADDRESS
        assert found[0].to_kind == check_vram_timing.ADDRESS

    def test_it_flags_two_adjacent_register_indirect_pokes(self, check_vram_timing):
        source = listing(
            instruction(0x100, "207c 003c 0000", "moveal #3932160,%a0"),
            instruction(0x106, "2080", "movel %d0,%a0@"),
            instruction(0x108, "2081", "movel %d1,%a0@"),
            instruction(0x10A, "4e75", "rts"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert len(found) == 1
        assert found[0].gap == 4

    def test_one_cheap_instruction_between_two_pokes_reaches_the_floor(self, check_vram_timing):
        source = listing(
            instruction(0x4D6, "23fc 74ba 1016", "movel #1958350870,3c0000 <x>"),
            continuation(0x4DC, "003c 0000"),
            instruction(0x4E0, "4e71", "nop"),
            instruction(0x4E2, "23c9 003c 0000", "movel %a1,3c0000 <x>"),
            instruction(0x4E8, "4e75", "rts"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert found == []


class TestPairsThatClearTheFloor:
    def test_the_stream_write_loop_passes(self, check_vram_timing):
        source = listing(
            instruction(0x226, "227c 003c 0002", "moveal #3932162,%a1"),
            instruction(0x22C, "3290", "movew %a0@,%a1@"),
            instruction(0x22E, "5888", "addql #4,%a0"),
            instruction(0x230, "32a8 fffe", "movew %a0@(-2),%a1@"),
            instruction(0x234, "b088", "cmpl %a0,%d0"),
            instruction(0x236, "66ee", "bnes 226 <x>"),
            instruction(0x238, "4e75", "rts"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert found == []

    def test_adjacent_long_immediate_pokes_pass(self, check_vram_timing):
        source = listing(
            instruction(0x126, "23fc 8001 0fff", "movel #-2147414017,3c0000 <x>"),
            continuation(0x12C, "003c 0000"),
            instruction(0x130, "23fc 8201 f80e", "movel #-2113800178,3c0000 <x>"),
            continuation(0x136, "003c 0000"),
            instruction(0x13A, "4e75", "rts"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert found == []

    def test_the_address_and_data_halves_of_one_long_write_are_not_a_pair(self, check_vram_timing):
        source = listing(
            instruction(0x100, "23c1 003c 0000", "movel %d1,3c0000 <x>"),
            instruction(0x106, "4e75", "rts"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert found == []

    def test_a_word_fill_loop_passes(self, check_vram_timing):
        source = listing(
            instruction(0x6C, "33fc 0000 003c", "movew #0,3c0002 <x>"),
            continuation(0x72, "0002"),
            instruction(0x74, "5342", "subqw #1,%d2"),
            instruction(0x76, "66f4", "bnes 6c <x>"),
            instruction(0x78, "4e75", "rts"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert found == []


class TestControlFlow:
    def test_it_follows_a_backward_branch_to_reach_the_next_write(self, check_vram_timing):
        source = listing(
            instruction(0x100, "207c 003c 0000", "moveal #3932160,%a0"),
            instruction(0x106, "2080", "movel %d0,%a0@"),
            instruction(0x108, "60fc", "bras 106 <x>"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert len(found) == 1
        assert found[0].gap == 14

    def test_a_return_between_two_writes_breaks_the_path(self, check_vram_timing):
        source = listing(
            instruction(0x100, "207c 003c 0000", "moveal #3932160,%a0"),
            instruction(0x106, "2080", "movel %d0,%a0@"),
            instruction(0x108, "4e75", "rts"),
            instruction(0x10A, "2081", "movel %d1,%a0@"),
        )

        found = check_vram_timing.analyse(source, "sample.o")

        assert found == []


class TestUnmodelledForms:
    def test_an_unrecognised_write_form_is_reported_rather_than_passed(self, check_vram_timing):
        source = listing(
            instruction(0x100, "33f0 0800 003c", "movew %a0@(0,%d0:l),3c0002 <x>"),
            continuation(0x106, "0002"),
            instruction(0x108, "4e75", "rts"),
        )

        with pytest.raises(check_vram_timing.UnmodelledAccessError):
            check_vram_timing.analyse(source, "sample.o")
