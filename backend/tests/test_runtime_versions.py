"""Guard against the runtime/CI version drift behind issue #574.

The Docker base images, the toolchain CI tests on, and the interpreter the hash-locked
requirements were compiled for must all name the same Python and Node majors; a bump
that lands in only one place ships a runtime CI never exercised.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LOCK_FILES = [
    REPO_ROOT / "backend" / "requirements.in",
    REPO_ROOT / "backend" / "requirements-dev.in",
    REPO_ROOT / "backend" / "requirements.txt",
    REPO_ROOT / "backend" / "requirements-dev.txt",
]


def _single(pattern: str, path: Path, flags: int = 0) -> str:
    matches = re.findall(pattern, path.read_text(), flags)
    assert len(matches) == 1, (
        f"expected exactly one match for {pattern!r} in {path}, got {matches}"
    )
    return matches[0]


def _all(pattern: str, path: Path) -> list[str]:
    matches = re.findall(pattern, path.read_text())
    assert matches, f"no match for {pattern!r} in {path}"
    return matches


def test_python_version_pinned_consistently():
    docker = _single(r"^FROM python:(\d+\.\d+)-slim@sha256:", DOCKERFILE, re.MULTILINE)
    ci = _all(r'python-version:\s*"(\d+\.\d+)"', CI_WORKFLOW)
    locks = {p.name: _single(r"--python-version (\d+\.\d+)", p) for p in LOCK_FILES}
    assert set(ci) == {docker}, (
        f"ci.yml python-version {ci} != Dockerfile python:{docker}-slim"
    )
    assert set(locks.values()) == {docker}, (
        f"requirements --python-version {locks} != Dockerfile python:{docker}-slim"
    )


def test_node_version_pinned_consistently():
    docker = _single(r"^FROM node:(\d+)-alpine@sha256:", DOCKERFILE, re.MULTILINE)
    ci = _all(r'node-version:\s*"(\d+)"', CI_WORKFLOW)
    assert set(ci) == {docker}, (
        f"ci.yml node-version {ci} != Dockerfile node:{docker}-alpine"
    )
