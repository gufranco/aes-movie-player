from __future__ import annotations

import pytest

from aesmovie import tiercache


@pytest.fixture(autouse=True)
def never_touch_the_committed_store(tmp_path, monkeypatch, request):
    """Keep the project's own tier file out of every test's reach.

    The store moved from a user cache to a tracked file at the top of
    the project, which put it one unstubbed call away from any test that
    exercises the search. A test that writes it corrupts a committed
    artefact and shows up as an unexplained diff rather than as a
    failure, so the redirect is automatic and opting out is explicit.
    """
    if request.node.get_closest_marker("reads_real_store"):
        return
    monkeypatch.setattr(tiercache, "default_store", lambda: tmp_path / "tiers.json")
