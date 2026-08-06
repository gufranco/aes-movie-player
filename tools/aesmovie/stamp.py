"""Keep the library header's version in step with the package's.

A release bumps `FMV_VERSION` in `src/fmv/fmv.h`, because that is the
one form python-semantic-release can rewrite in a C header. The numeric
major and minor beside it are what the generated movie header compares
against at compile time, and the preprocessor cannot split a string, so
they are rewritten from it here.

The release runs this as its build command. Anyone can run it by hand;
running it when nothing has moved rewrites nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

HEADER: Final = Path(__file__).resolve().parents[2] / "src" / "fmv" / "fmv.h"

_VERSION: Final = re.compile(r'^#define FMV_VERSION "(?P<major>\d+)\.(?P<minor>\d+)\.\d+"$', re.M)
_MAJOR: Final = re.compile(r"^#define FMV_VERSION_MAJOR \d+$", re.M)
_MINOR: Final = re.compile(r"^#define FMV_VERSION_MINOR \d+$", re.M)


def restamp(text: str) -> str:
    """Rewrite the numeric defines from the version string above them."""
    found = _VERSION.search(text)
    if found is None:
        msg = 'src/fmv/fmv.h carries no `#define FMV_VERSION "x.y.z"` to read'
        raise SystemExit(msg)
    for pattern, name in ((_MAJOR, "MAJOR"), (_MINOR, "MINOR")):
        if pattern.search(text) is None:
            msg = f"src/fmv/fmv.h carries no `#define FMV_VERSION_{name}` to rewrite"
            raise SystemExit(msg)
    text = _MAJOR.sub(f"#define FMV_VERSION_MAJOR {found['major']}", text, count=1)
    return _MINOR.sub(f"#define FMV_VERSION_MINOR {found['minor']}", text, count=1)


def main(argv: list[str]) -> int:
    header = Path(argv[0]) if argv else HEADER
    before = header.read_text()
    after = restamp(before)
    if after != before:
        header.write_text(after)
        print(f"restamped {header}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
