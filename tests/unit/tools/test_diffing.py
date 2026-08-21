from __future__ import annotations

from tools.diffing import MAX_DIFF_CHARS, compute_diff


def test_identical_content_produces_empty_diff() -> None:
    result = compute_diff("a.txt", "same\n", "same\n")
    assert result.diff == ""
    assert result.truncated is False


def test_creation_diff_uses_dev_null_as_source() -> None:
    result = compute_diff("a.txt", None, "new content\n")
    assert "/dev/null" in result.diff
    assert "+new content" in result.diff


def test_deletion_diff_uses_dev_null_as_destination() -> None:
    result = compute_diff("a.txt", "old content\n", None)
    assert "/dev/null" in result.diff
    assert "-old content" in result.diff


def test_modification_diff_shows_both_sides() -> None:
    result = compute_diff("a.txt", "line1\nline2\n", "line1\nchanged\n")
    assert "-line2" in result.diff
    assert "+changed" in result.diff
    assert "line1" in result.diff


def test_diff_is_bounded() -> None:
    huge_before = "\n".join(f"line {i}" for i in range(10_000))
    huge_after = "\n".join(f"line {i}!" for i in range(10_000))
    result = compute_diff("big.txt", huge_before, huge_after)
    assert result.truncated is True
    assert len(result.diff) <= MAX_DIFF_CHARS + 100
