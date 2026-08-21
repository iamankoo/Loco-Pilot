"""Deterministic language/framework/test-framework detection from real
repository evidence — manifest presence and parsed dependency names, never
a guess and never something the LLM is asked to "just know".

Language, framework, and test-framework detection are kept as separate
concerns (separate functions, separate evidence trails) per the Phase 2.2
spec, even though `detect_project_type` composes all three, so each is
independently testable and extensible without the others changing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from analysis.manifests import DependencySummary
from analysis.scanner import RepositoryStructure

# manifest filename -> language, in priority order (first match wins the
# "primary evidence" slot, but every match is still recorded as evidence).
_LANGUAGE_MARKERS: list[tuple[str, str]] = [
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
    ("setup.py", "Python"),
    ("setup.cfg", "Python"),
    ("Pipfile", "Python"),
    ("package.json", "JavaScript/TypeScript"),
    ("tsconfig.json", "JavaScript/TypeScript"),
    ("pom.xml", "Java"),
    ("build.gradle", "Java"),
    ("build.gradle.kts", "Java"),
    ("go.mod", "Go"),
    ("Cargo.toml", "Rust"),
    ("pubspec.yaml", "Dart/Flutter"),
    ("CMakeLists.txt", "C/C++"),
    ("Makefile", "C/C++"),
]

_EXTENSION_LANGUAGE_HINTS = {
    ".py": "Python", ".js": "JavaScript/TypeScript", ".jsx": "JavaScript/TypeScript",
    ".ts": "JavaScript/TypeScript", ".tsx": "JavaScript/TypeScript", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".dart": "Dart/Flutter", ".c": "C/C++", ".cpp": "C/C++",
    ".cc": "C/C++", ".h": "C/C++", ".hpp": "C/C++", ".kt": "Kotlin",
}

# dependency name -> framework, checked against the parsed dependency list
# (never against just a filename) so a weak filename alone never claims a
# framework stronger evidence would contradict.
_PYTHON_FRAMEWORK_DEPS = {
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
}
_PYTHON_TEST_DEPS = {"pytest": "pytest"}

_NODE_FRAMEWORK_DEPS = {
    "next": "Next.js", "react": "React", "express": "Express",
    "@nestjs/core": "NestJS", "vue": "Vue", "react-native": "React Native",
}
_NODE_TEST_DEPS = {
    "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha",
    "playwright": "Playwright", "@playwright/test": "Playwright", "cypress": "Cypress",
}

_JAVA_FRAMEWORK_MARKERS = {"spring-boot": "Spring Boot", "spring-boot-starter": "Spring Boot"}


class ProjectTypeDetection(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    test_frameworks: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


def _detect_languages(structure: RepositoryStructure) -> tuple[list[str], list[str]]:
    languages: list[str] = []
    evidence: list[str] = []
    top_level_files = {f for f in structure.files if "/" not in f}

    for marker, language in _LANGUAGE_MARKERS:
        if marker in top_level_files or marker in structure.dependency_manifests:
            if language not in languages:
                languages.append(language)
            evidence.append(marker)

    if not languages:
        # No manifest at all: fall back to counting source-file extensions
        # actually present, so "detected" still means real file evidence.
        seen_exts: set[str] = set()
        for f in structure.files:
            for ext, language in _EXTENSION_LANGUAGE_HINTS.items():
                if f.endswith(ext) and ext not in seen_exts:
                    seen_exts.add(ext)
                    if language not in languages:
                        languages.append(language)
                    evidence.append(f"file extension {ext}")

    return languages, evidence


def _detect_frameworks(deps: DependencySummary) -> tuple[list[str], list[str]]:
    frameworks: list[str] = []
    evidence: list[str] = []
    all_deps = {name.lower() for name in deps.direct_dependencies + deps.dev_dependencies}

    for dep_name, framework in _PYTHON_FRAMEWORK_DEPS.items():
        if dep_name in all_deps:
            frameworks.append(framework)
            evidence.append(f"dependency: {dep_name}")

    for dep_name, framework in _NODE_FRAMEWORK_DEPS.items():
        if dep_name.lower() in all_deps:
            if framework == "React" and "Next.js" in frameworks:
                continue  # Next.js already implies React; avoid double-reporting the same evidence.
            frameworks.append(framework)
            evidence.append(f"dependency: {dep_name}")

    for coordinate in deps.direct_dependencies:
        lowered = coordinate.lower()
        for marker, framework in _JAVA_FRAMEWORK_MARKERS.items():
            if marker in lowered and framework not in frameworks:
                frameworks.append(framework)
                evidence.append(f"dependency: {coordinate}")

    if "pubspec.yaml" in deps.manifests_parsed and "Flutter" not in frameworks:
        frameworks.append("Flutter")
        evidence.append("manifest: pubspec.yaml")

    return frameworks, evidence


def _detect_test_frameworks(structure: RepositoryStructure, deps: DependencySummary) -> tuple[list[str], list[str]]:
    test_frameworks: list[str] = []
    evidence: list[str] = []
    all_deps = {name.lower() for name in deps.direct_dependencies + deps.dev_dependencies}

    for dep_name, framework in {**_PYTHON_TEST_DEPS, **_NODE_TEST_DEPS}.items():
        if dep_name.lower() in all_deps:
            test_frameworks.append(framework)
            evidence.append(f"dependency: {dep_name}")

    if any(c.lower() in all_deps for c in ("junit", "junit5", "org.junit.jupiter:junit-jupiter")):
        test_frameworks.append("JUnit")
        evidence.append("dependency: junit")

    if "go.mod" in deps.manifests_parsed and any(f.endswith("_test.go") for f in structure.files):
        test_frameworks.append("go test")
        evidence.append("*_test.go files present")

    if "Cargo.toml" in deps.manifests_parsed:
        test_frameworks.append("cargo test")
        evidence.append("manifest: Cargo.toml")

    if any(f == "CMakeLists.txt" for f in structure.dependency_manifests):
        test_frameworks.append("CTest")
        evidence.append("manifest: CMakeLists.txt")

    if "pubspec.yaml" in deps.manifests_parsed and any(f.endswith("_test.dart") for f in structure.files):
        test_frameworks.append("flutter test")
        evidence.append("*_test.dart files present")

    if not test_frameworks and "Python" in _languages_from_manifests(deps) and any(
        f.startswith("test_") or f.endswith("_test.py") or "/test_" in f for f in structure.files
    ):
        test_frameworks.append("unittest")
        evidence.append("test_*.py files present, no test framework dependency found")

    return sorted(dict.fromkeys(test_frameworks)), evidence


def _languages_from_manifests(deps: DependencySummary) -> set[str]:
    return {"Python"} if "pip" in deps.package_managers or "poetry" in deps.package_managers else set()


def detect_project_type(structure: RepositoryStructure, dependencies: DependencySummary) -> ProjectTypeDetection:
    languages, language_evidence = _detect_languages(structure)
    frameworks, framework_evidence = _detect_frameworks(dependencies)
    test_frameworks, test_evidence = _detect_test_frameworks(structure, dependencies)

    evidence = list(dict.fromkeys(language_evidence + dependencies.manifests_parsed + framework_evidence + test_evidence))

    return ProjectTypeDetection(
        languages=languages,
        frameworks=frameworks,
        test_frameworks=test_frameworks,
        package_managers=dependencies.package_managers,
        evidence=evidence,
    )
