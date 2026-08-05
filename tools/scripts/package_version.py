"""Print the version the package declares.

The release workflow refuses a tag that disagrees with this, so a tag
can never name a version the tree does not carry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "pyproject.toml"


def package_version(manifest: Path = MANIFEST) -> str:
    """The version string from the packaging manifest."""
    parsed = tomllib.loads(manifest.read_text())
    version = parsed["project"]["version"]
    if not isinstance(version, str):
        message = f"{manifest} declares a non-string version: {version!r}"
        raise TypeError(message)
    return version


if __name__ == "__main__":
    print(package_version())
