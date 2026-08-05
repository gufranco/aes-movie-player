from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import package_version


class TestReadingTheDeclaredVersion:
    def test_it_reads_what_the_manifest_declares(self, tmp_path):
        manifest = tmp_path / "pyproject.toml"
        manifest.write_text('[project]\nname = "x"\nversion = "1.2.3"\n')

        assert package_version.package_version(manifest) == "1.2.3"

    def test_the_real_manifest_carries_a_version(self):
        assert package_version.package_version().count(".") >= 1

    def test_a_manifest_with_no_version_is_an_error_rather_than_a_blank(self, tmp_path):
        manifest = tmp_path / "pyproject.toml"
        manifest.write_text('[project]\nname = "x"\n')

        with pytest.raises(KeyError):
            package_version.package_version(manifest)

    def test_a_non_string_version_is_refused(self, tmp_path):
        manifest = tmp_path / "pyproject.toml"
        manifest.write_text('[project]\nname = "x"\nversion = 3\n')

        with pytest.raises(TypeError):
            package_version.package_version(manifest)
