from __future__ import annotations

from analysis.scanner import RepositoryStructure
from analysis.test_selection import select_test_targets


def _structure(files: list[str], test_directories: list[str] | None = None) -> RepositoryStructure:
    return RepositoryStructure(root=".", files=files, test_directories=test_directories or [])


def test_selects_tests_matching_the_changed_files_directory() -> None:
    structure = _structure(
        ["auth/jwt.py", "payments/stripe.py", "tests/test_auth.py", "tests/test_payments.py"],
        test_directories=["tests"],
    )
    targets = select_test_targets(structure, changed_files=["auth/jwt.py"], task="Fix JWT authentication")
    assert targets == ["tests/test_auth.py"]


def test_selects_tests_matching_task_keywords_alone() -> None:
    structure = _structure(["tests/test_auth.py", "tests/test_payments.py"], test_directories=["tests"])
    targets = select_test_targets(structure, task="Fix the authentication flow")
    assert targets == ["tests/test_auth.py"]


def test_returns_empty_when_nothing_matches() -> None:
    structure = _structure(["tests/test_billing.py"], test_directories=["tests"])
    targets = select_test_targets(structure, changed_files=["auth/jwt.py"], task="Fix JWT authentication")
    assert targets == []


def test_returns_empty_when_no_test_files_exist() -> None:
    structure = _structure(["app.py"])
    targets = select_test_targets(structure, changed_files=["app.py"], task="fix app")
    assert targets == []


def test_returns_empty_for_none_structure() -> None:
    assert select_test_targets(None, changed_files=["a.py"], task="x") == []


def test_results_are_bounded() -> None:
    files = [f"tests/test_auth_{i}.py" for i in range(10)]
    structure = _structure(files, test_directories=["tests"])
    targets = select_test_targets(structure, task="Fix authentication", max_targets=3)
    assert len(targets) == 3


def test_exact_stem_match_ranks_above_a_directory_only_match() -> None:
    structure = _structure(
        ["auth/jwt.py", "tests/test_jwt.py", "tests/test_auth_helpers.py"], test_directories=["tests"]
    )
    targets = select_test_targets(structure, changed_files=["auth/jwt.py"], task="fix it")
    assert targets[0] == "tests/test_jwt.py"
