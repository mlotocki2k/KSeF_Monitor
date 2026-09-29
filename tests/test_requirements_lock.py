"""
The Docker image installs requirements.lock (hash-pinned). Every requirement
from requirements.txt must be pinned there, at a version its specifier allows,
with hashes — otherwise the lock silently drifts from the declared ranges.
"""

import re
from pathlib import Path

import pytest

packaging = pytest.importorskip("packaging")
from packaging.requirements import Requirement  # noqa: E402
from packaging.utils import canonicalize_name  # noqa: E402

ROOT = Path(__file__).parent.parent


def _requirements():
    reqs = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            reqs.append(Requirement(line))
    return reqs


def _lock():
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins, hashed = {}, set()
    current = None
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s;\\]+)", line)
        if m:
            current = canonicalize_name(m.group(1).split("[")[0])
            pins[current] = m.group(2)
        elif current and "--hash=sha256:" in line:
            hashed.add(current)
    return pins, hashed


def test_every_requirement_pinned_within_its_range():
    pins, _ = _lock()
    problems = []
    for req in _requirements():
        name = canonicalize_name(req.name)
        if name not in pins:
            problems.append(f"{req.name}: missing from requirements.lock")
        elif not req.specifier.contains(pins[name], prereleases=True):
            problems.append(f"{req.name}: lock has {pins[name]}, requirements.txt wants {req.specifier}")
    assert not problems, "regenerate requirements.lock:\n" + "\n".join(problems)


def test_every_lock_entry_has_hashes():
    pins, hashed = _lock()
    assert set(pins) == hashed
