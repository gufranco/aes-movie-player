from __future__ import annotations

import pytest

from aesmovie import bake, stamp

HEADER = """#ifndef FMV_H
#define FMV_H

#define FMV_VERSION "2.7.3"
#define FMV_VERSION_MAJOR 1
#define FMV_VERSION_MINOR 0

#endif
"""


class TestRestamping:
    def test_it_takes_the_major_from_the_version_string(self):
        assert "#define FMV_VERSION_MAJOR 2" in stamp.restamp(HEADER)

    def test_it_takes_the_minor_from_the_version_string(self):
        assert "#define FMV_VERSION_MINOR 7" in stamp.restamp(HEADER)

    def test_it_leaves_the_version_string_alone(self):
        assert '#define FMV_VERSION "2.7.3"' in stamp.restamp(HEADER)

    def test_it_leaves_the_rest_of_the_header_alone(self):
        text = stamp.restamp(HEADER)

        assert text.startswith("#ifndef FMV_H")
        assert text.endswith("#endif\n")

    def test_restamping_an_already_current_header_changes_nothing(self):
        current = stamp.restamp(HEADER)

        assert stamp.restamp(current) == current

    def test_a_header_without_a_version_string_is_an_error(self):
        with pytest.raises(SystemExit, match="FMV_VERSION"):
            stamp.restamp("#define FMV_VERSION_MAJOR 1\n")

    def test_a_header_without_the_numeric_defines_is_an_error(self):
        with pytest.raises(SystemExit, match="FMV_VERSION_MAJOR"):
            stamp.restamp('#define FMV_VERSION "1.0.0"\n')


class TestTheCommandLine:
    def test_it_rewrites_the_header_in_place(self, tmp_path):
        header = tmp_path / "fmv.h"
        header.write_text(HEADER)

        code = stamp.main([str(header)])

        assert code == 0
        assert "#define FMV_VERSION_MAJOR 2" in header.read_text()

    def test_it_reports_nothing_when_the_header_is_already_current(self, tmp_path, capsys):
        header = tmp_path / "fmv.h"
        header.write_text(stamp.restamp(HEADER))

        stamp.main([str(header)])

        assert capsys.readouterr().out == ""


class TestTheShippedHeader:
    def test_the_repository_header_is_already_stamped(self):
        text = stamp.HEADER.read_text()

        assert stamp.restamp(text) == text

    def test_it_states_the_version_the_package_states(self):
        text = stamp.HEADER.read_text()
        major, minor = bake.baker_version()

        assert f'#define FMV_VERSION "{major}.{minor}.' in text
