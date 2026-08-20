from __future__ import annotations

from backend.app.db.repositories.truncate import truncate_for_storage


def test_truncate_short_string_untouched() -> None:
    assert truncate_for_storage("short") == "short"


def test_truncate_long_string_is_capped() -> None:
    result = truncate_for_storage("a" * 10_000, limit=100)
    assert len(result) < 10_000
    assert result.startswith("a" * 100)
    assert "truncated" in result


def test_truncate_recurses_into_dict_and_list() -> None:
    payload = {"a": "x" * 100, "b": ["y" * 100, "short"]}
    result = truncate_for_storage(payload, limit=10)
    assert len(result["a"]) < 100
    assert len(result["b"][0]) < 100
    assert result["b"][1] == "short"


def test_truncate_passes_through_non_string_scalars() -> None:
    assert truncate_for_storage(42) == 42
    assert truncate_for_storage(None) is None
    assert truncate_for_storage(True) is True
