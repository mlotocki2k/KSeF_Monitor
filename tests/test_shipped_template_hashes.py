"""
entrypoint.sh refreshes template copies in /data only when they match a
released default listed in app/templates/shipped_defaults.sha256. Every
current template must be listed, or its fixes never reach existing installs.
"""

import hashlib
from pathlib import Path

TEMPLATES = Path(__file__).parent.parent / "app" / "templates"


def _listed():
    pairs = set()
    for line in (TEMPLATES / "shipped_defaults.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(maxsplit=1)
            pairs.add((digest, name.strip()))
    return pairs


def test_every_current_template_is_listed():
    listed = _listed()
    missing = [
        p.name for p in sorted(TEMPLATES.glob("*.j2"))
        if (hashlib.sha256(p.read_bytes()).hexdigest(), p.name) not in listed
    ]
    assert not missing, (
        f"append to app/templates/shipped_defaults.sha256: "
        + ", ".join(f"$(sha256sum app/templates/{m})" for m in missing)
    )
