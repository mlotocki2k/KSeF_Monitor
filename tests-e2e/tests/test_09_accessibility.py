"""
Accessibility tests - axe-core scan.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page


REPORTS_DIR = Path(__file__).parent.parent / "reports"


def run_axe(page: Page) -> dict:
    """Wstrzykuje axe-core i uruchamia scan."""
    try:
        from axe_playwright_python.sync_playwright import Axe
        axe = Axe()
        results = axe.run(page)
        return results.response  # dict z violations, passes, etc.
    except ImportError:
        # Fallback - inline axe via CDN
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js")
        results = page.evaluate("""
            async () => {
                const r = await axe.run(document, {
                    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] }
                });
                return r;
            }
        """)
        return results


@pytest.mark.a11y
@pytest.mark.public
class TestAccessibilityPublic:
    """A11y na publicznych stronach."""

    def test_login_page_a11y(self, page: Page):
        page.goto("/ui/login")
        page.wait_for_load_state("networkidle")
        results = run_axe(page)

        violations = results.get("violations", [])
        report_path = REPORTS_DIR / "a11y_login.json"
        report_path.parent.mkdir(exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(violations, f, indent=2, ensure_ascii=False)

        critical = [v for v in violations if v.get("impact") in ("critical", "serious")]
        if critical:
            print("\n[A11y] Krytyczne violations:")
            for v in critical:
                print(f"  - {v['id']}: {v['help']} ({len(v['nodes'])} nodes)")

        # Soft - tylko na critical/serious failujemy
        assert not critical, f"Krytyczne A11y issues: {[v['id'] for v in critical]}"


@pytest.mark.a11y
@pytest.mark.auth
class TestAccessibilityAuthed:
    """A11y na zalogowanych stronach."""

    @pytest.mark.parametrize("path,name", [
        ("/ui", "dashboard"),
        ("/ui/invoices", "invoices_list"),
        ("/ui/account", "account"),
    ])
    def test_authed_page_a11y(self, authed_page: Page, path: str, name: str):
        authed_page.goto(path)
        authed_page.wait_for_load_state("networkidle")
        results = run_axe(authed_page)

        violations = results.get("violations", [])
        report_path = REPORTS_DIR / f"a11y_{name}.json"
        report_path.parent.mkdir(exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(violations, f, indent=2, ensure_ascii=False)

        critical = [v for v in violations if v.get("impact") == "critical"]
        if critical:
            print(f"\n[A11y {name}] Krytyczne:")
            for v in critical:
                print(f"  - {v['id']}: {v['help']}")

        assert not critical, f"Critical A11y na {path}: {[v['id'] for v in critical]}"
