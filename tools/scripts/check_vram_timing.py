from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

VRAM_ADDRESS_PORT = 0x3C0000
VRAM_DATA_PORT = 0x3C0002
VRAM_MODULO_PORT = 0x3C0004
VRAM_PORTS = (VRAM_ADDRESS_PORT, VRAM_DATA_PORT, VRAM_MODULO_PORT)

MIN_CYCLES_DATA_TO_DATA = 12
MIN_CYCLES_DATA_TO_ADDRESS = 16
BUS_CYCLE_LENGTH = 4
SEARCH_CEILING_CYCLES = 2 * MIN_CYCLES_DATA_TO_ADDRESS
MINIMUM_INSTRUCTION_CYCLES = 4

ADDRESS = "address"
DATA = "data"
MODULO = "modulo"

PORT_KIND = {
    VRAM_ADDRESS_PORT: ADDRESS,
    VRAM_DATA_PORT: DATA,
    VRAM_MODULO_PORT: MODULO,
}

LINE = re.compile(r"^\s*([0-9a-f]+):\t([0-9a-f ]+?)\s*(?:\t(.*))?$")
SECTION = re.compile(r"^Disassembly of section (\S+):")
SYMBOL = re.compile(r"^([0-9a-f]{8}) <(.+)>:")
PORT_INTO_REGISTER = re.compile(r"^moveal\s+#(\d+),%(a[0-7])$")
ABSOLUTE_WRITE = re.compile(r"^move([lw])\s+(.+?),([0-9a-f]{6})\b")
INDIRECT_WRITE = re.compile(r"^move([lw])\s+(.+?),%(a[0-7])@$")
REGISTER_CLOBBER = re.compile(r",%(a[0-7])\b")
BRANCH_TARGET = re.compile(r"\b([0-9a-f]+)\s+<")
PLAIN_REGISTER = re.compile(r"%[da][0-7]")
PLAIN_INDIRECT = re.compile(r"%a[0-7]@")
DISPLACED_INDIRECT = re.compile(r"%a[0-7]@\(-?\d+\)")

UNCONDITIONAL = ("bra", "jmp")
CALL = ("bsr", "jsr")
BIT_OPERATION = ("bset", "btst", "bclr", "bchg")

BRANCH_ALWAYS_CYCLES = 10
BRANCH_CONDITIONAL_CYCLES = 8
DECREMENT_BRANCH_CYCLES = 10

CYCLE_TABLE = {
    "moveq": 4,
    "swap": 4,
    "extl": 4,
    "extw": 4,
    "clrw": 4,
    "clrl": 6,
    "tstb": 4,
    "tstw": 4,
    "tstl": 4,
    "nop": 4,
    "addqw": 4,
    "subqw": 4,
    "addql": 8,
    "subql": 8,
    "addiw": 8,
    "subiw": 8,
    "andiw": 8,
    "oriw": 8,
    "cmpiw": 8,
    "cmpib": 8,
    "addil": 16,
    "subil": 16,
    "andil": 16,
    "oril": 16,
    "cmpil": 14,
    "cmpw": 4,
    "cmpl": 6,
    "addw": 4,
    "addl": 8,
    "orw": 4,
    "orl": 8,
    "andw": 4,
    "andl": 8,
    "lslw": 6,
    "lsrw": 6,
    "lsll": 8,
    "lsrl": 8,
    "pea": 12,
    "jsr": 18,
    "bsrs": 18,
    "rts": 16,
}


class UnmodelledAccessError(Exception):
    pass


def cycles_for(mnemonic: str) -> int:
    if mnemonic in CYCLE_TABLE:
        return CYCLE_TABLE[mnemonic]
    if mnemonic.startswith(UNCONDITIONAL):
        return BRANCH_ALWAYS_CYCLES
    if mnemonic.startswith("db"):
        return DECREMENT_BRANCH_CYCLES
    if mnemonic.startswith("b") and not mnemonic.startswith(BIT_OPERATION + CALL):
        return BRANCH_CONDITIONAL_CYCLES
    return MINIMUM_INSTRUCTION_CYCLES


@dataclass(frozen=True)
class Access:
    kind: str
    offset: int


@dataclass
class Instruction:
    address: int
    text: str
    cycles: int = MINIMUM_INSTRUCTION_CYCLES
    accesses: tuple[Access, ...] = ()
    successors: tuple[int, ...] = ()

    @property
    def mnemonic(self) -> str:
        return self.text.split()[0] if self.text else ""


@dataclass(frozen=True)
class Violation:
    label: str
    symbol: str
    source: Instruction
    target: Instruction
    from_kind: str
    to_kind: str
    gap: int
    floor: int


def absolute_write_profile(long_move: bool, source: str) -> tuple[int, tuple[int, ...]]:
    immediate = source.startswith("#")
    register = PLAIN_REGISTER.fullmatch(source) is not None
    indirect = PLAIN_INDIRECT.fullmatch(source) is not None

    if long_move:
        if immediate:
            return 28, (20, 24)
        if register:
            return 20, (12, 16)
        raise UnmodelledAccessError(f"long absolute write from {source!r}")
    if immediate or register or indirect:
        return 20, (16,)
    raise UnmodelledAccessError(f"word absolute write from {source!r}")


def indirect_write_profile(long_move: bool, source: str) -> tuple[int, tuple[int, ...]]:
    register = PLAIN_REGISTER.fullmatch(source) is not None
    indirect = PLAIN_INDIRECT.fullmatch(source) is not None
    displaced = DISPLACED_INDIRECT.fullmatch(source) is not None

    if long_move:
        if register:
            return 12, (4, 8)
        raise UnmodelledAccessError(f"long register indirect write from {source!r}")
    if register:
        return 8, (4,)
    if indirect:
        return 12, (8,)
    if displaced:
        return 16, (12,)
    raise UnmodelledAccessError(f"word register indirect write from {source!r}")


def kinds_for(long_move: bool, port: int) -> tuple[str, ...]:
    return (ADDRESS, DATA) if long_move else (PORT_KIND[port],)


def split_sections(text: str) -> Iterator[tuple[str, list[Instruction], list[tuple[int, str]]]]:
    section = ""
    entries: list[Instruction] = []
    symbols: list[tuple[int, str]] = []

    for raw in text.splitlines():
        header = SECTION.match(raw)
        if header:
            if entries:
                yield section, entries, symbols
            section, entries, symbols = header.group(1), [], []
            continue
        named = SYMBOL.match(raw)
        if named:
            symbols.append((int(named.group(1), 16), named.group(2)))
            continue
        matched = LINE.match(raw)
        if matched and matched.group(3):
            entries.append(Instruction(int(matched.group(1), 16), matched.group(3).strip()))

    if entries:
        yield section, entries, symbols


def annotate(entries: list[Instruction]) -> None:
    held: dict[str, int] = {}

    for instruction in entries:
        text = instruction.text
        instruction.cycles = cycles_for(instruction.mnemonic)

        loaded = PORT_INTO_REGISTER.match(text)
        if loaded:
            value = int(loaded.group(1))
            if value in VRAM_PORTS:
                held[loaded.group(2)] = value
            else:
                held.pop(loaded.group(2), None)
            continue

        absolute = ABSOLUTE_WRITE.match(text)
        if absolute and int(absolute.group(3), 16) in VRAM_PORTS:
            long_move = absolute.group(1) == "l"
            port = int(absolute.group(3), 16)
            cycles, offsets = absolute_write_profile(long_move, absolute.group(2).strip())
            instruction.cycles = cycles
            instruction.accesses = tuple(
                Access(kind, offset)
                for kind, offset in zip(kinds_for(long_move, port), offsets, strict=True)
            )
            continue

        indirect = INDIRECT_WRITE.match(text)
        if indirect and indirect.group(3) in held:
            long_move = indirect.group(1) == "l"
            port = held[indirect.group(3)]
            cycles, offsets = indirect_write_profile(long_move, indirect.group(2).strip())
            instruction.cycles = cycles
            instruction.accesses = tuple(
                Access(kind, offset)
                for kind, offset in zip(kinds_for(long_move, port), offsets, strict=True)
            )
            continue

        for register in REGISTER_CLOBBER.findall(text):
            held.pop(register, None)
        if instruction.mnemonic.startswith("movem"):
            held.clear()


def connect(entries: list[Instruction]) -> dict[int, Instruction]:
    index = {instruction.address: instruction for instruction in entries}

    for position, instruction in enumerate(entries):
        mnemonic = instruction.mnemonic
        following = entries[position + 1].address if position + 1 < len(entries) else None
        matched = BRANCH_TARGET.search(instruction.text)
        target = int(matched.group(1), 16) if matched else None
        successors: list[int] = []

        if mnemonic.startswith("rts"):
            successors = []
        elif mnemonic.startswith(CALL):
            if following is not None:
                successors.append(following)
        elif mnemonic.startswith(UNCONDITIONAL):
            if target is not None and target in index:
                successors.append(target)
        else:
            if mnemonic.startswith(("b", "db")) and target is not None and target in index:
                successors.append(target)
            if following is not None:
                successors.append(following)

        instruction.successors = tuple(successors)

    return index


def floor_between(from_kind: str, to_kind: str) -> int | None:
    if from_kind != DATA:
        return None
    if to_kind == DATA:
        return MIN_CYCLES_DATA_TO_DATA
    if to_kind in (ADDRESS, MODULO):
        return MIN_CYCLES_DATA_TO_ADDRESS
    return None


def downstream(
    index: dict[int, Instruction], start: Instruction, carried: int
) -> Iterator[tuple[Instruction, int]]:
    frontier = [(address, carried) for address in start.successors]
    seen: set[tuple[int, int]] = set()

    while frontier:
        address, spent = frontier.pop()
        if spent >= SEARCH_CEILING_CYCLES or (address, spent) in seen:
            continue
        seen.add((address, spent))
        instruction = index.get(address)
        if instruction is None:
            continue
        if instruction.accesses:
            yield instruction, spent
            continue
        frontier.extend(
            (successor, spent + instruction.cycles) for successor in instruction.successors
        )


def name_at(symbols: list[tuple[int, str]], address: int) -> str:
    name = "?"
    for start, candidate in symbols:
        if start <= address:
            name = candidate
    return name


def inspect(
    label: str, entries: list[Instruction], symbols: list[tuple[int, str]]
) -> list[Violation]:
    index = connect(entries)
    violations: list[Violation] = []

    for instruction in entries:
        for position, access in enumerate(instruction.accesses):
            if access.kind != DATA:
                continue
            symbol = name_at(symbols, instruction.address)
            remaining = instruction.accesses[position + 1 :]
            if remaining:
                gap = remaining[0].offset - (access.offset + BUS_CYCLE_LENGTH)
                limit = floor_between(DATA, remaining[0].kind)
                if limit is not None and gap < limit:
                    violations.append(
                        Violation(
                            label,
                            symbol,
                            instruction,
                            instruction,
                            DATA,
                            remaining[0].kind,
                            gap,
                            limit,
                        )
                    )
                continue
            carried = instruction.cycles - (access.offset + BUS_CYCLE_LENGTH)
            for reached, spent in downstream(index, instruction, carried):
                arriving = reached.accesses[0]
                limit = floor_between(DATA, arriving.kind)
                if limit is None:
                    continue
                gap = spent + arriving.offset
                if gap < limit:
                    violations.append(
                        Violation(
                            label, symbol, instruction, reached, DATA, arriving.kind, gap, limit
                        )
                    )

    return violations


def analyse(listing: str, label: str) -> list[Violation]:
    violations: list[Violation] = []

    for section, entries, symbols in split_sections(listing):
        annotate(entries)
        violations.extend(inspect(f"{label}:{section}", entries, symbols))

    return violations


def disassemble(objdump: str, path: Path) -> str:
    return subprocess.run(
        [objdump, "-d", str(path)], check=True, capture_output=True, text=True
    ).stdout


def report(objdump: str, paths: list[Path]) -> int:
    violations: list[Violation] = []

    for path in paths:
        violations.extend(analyse(disassemble(objdump, path), path.name))

    if not violations:
        print(
            f"VRAM write spacing clears the {MIN_CYCLES_DATA_TO_DATA} and "
            f"{MIN_CYCLES_DATA_TO_ADDRESS} cycle minimums across {len(paths)} object(s)"
        )
        return 0

    for violation in violations:
        print(
            f"{violation.label} {violation.symbol}: {violation.from_kind} write to "
            f"{violation.to_kind} write is {violation.gap} cycles, needs {violation.floor}",
            file=sys.stderr,
        )
        print(f"    {violation.source.address:#06x}: {violation.source.text}", file=sys.stderr)
        print(f"    {violation.target.address:#06x}: {violation.target.text}", file=sys.stderr)

    print(f"{len(violations)} VRAM write pair(s) under the minimum", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("objects", nargs="+", type=Path)
    parser.add_argument("--objdump", default="m68k-neogeo-elf-objdump")
    arguments = parser.parse_args(argv)

    try:
        return report(arguments.objdump, arguments.objects)
    except UnmodelledAccessError as error:
        print(f"unmodelled VRAM write form: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
