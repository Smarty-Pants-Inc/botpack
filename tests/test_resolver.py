from __future__ import annotations

import pytest

from botpack.resolver import parse_semver, pick_highest_satisfying, satisfies


def test_parse_semver() -> None:
    assert parse_semver("1.2.3").major == 1
    with pytest.raises(ValueError):
        parse_semver("1.2")


def test_satisfies_exact_and_caret() -> None:
    assert satisfies(parse_semver("1.2.3"), "1.2.3")
    assert not satisfies(parse_semver("1.2.4"), "1.2.3")

    assert satisfies(parse_semver("1.5.0"), "^1.2.3")
    assert not satisfies(parse_semver("2.0.0"), "^1.2.3")


def test_pick_highest_satisfying() -> None:
    versions = ["1.2.3", "1.4.0", "2.0.0"]
    assert pick_highest_satisfying(versions, "^1.2.3") == "1.4.0"
    assert pick_highest_satisfying(versions, "1.2.3") == "1.2.3"
    assert pick_highest_satisfying(versions, "^3.0.0") is None
