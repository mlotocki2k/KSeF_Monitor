"""Ensure pyproject.toml version matches app.__version__."""
import sys
from pathlib import Path

import pytest

from app import __version__

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


@pytest.mark.skipif(tomllib is None, reason="tomllib/tomli not available (Python < 3.11 without tomli installed)")
def test_version_matches_pyproject():
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__, (
        f"pyproject.toml version={data['project']['version']} "
        f"does not match app.__version__={__version__}"
    )
