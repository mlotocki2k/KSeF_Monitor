"""
Generuje konsolidowany raport HTML z wszystkich JSONow + pytest-html.
Zbiera:
- explorer_*.json (crawl results)
- a11y_*.json (axe violations)
- screenshots/
- pytest report.html
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


REPORTS = Path(__file__).parent.parent / "reports"
SCREENSHOTS = Path(__file__).parent.parent / "screenshots"


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def render_html() -> str:
    explorer_authed = load_json(REPORTS / "explorer_authed.json")
    explorer_public = load_json(REPORTS / "explorer_public.json")
    a11y_files = list(REPORTS.glob("a11y_*.json"))
    screenshots = sorted(SCREENSHOTS.glob("*.png"))

    html = ["""<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>AI Tester KSeF Monitor — Raport</title>
<style>
body { font-family: system-ui, -apple-system, sans-serif; background: #0B1A3E; color: #fff; max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
h1 { color: #34C759; }
h2 { color: #007AFF; border-bottom: 1px solid #243454; padding-bottom: .5rem; margin-top: 2rem; }
h3 { color: #8E99AF; }
.card { background: #1A2B50; border: 1px solid #243454; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
.ok { color: #34C759; }
.warn { color: #FF9500; }
.err { color: #FF3B30; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: .5rem; border-bottom: 1px solid #243454; }
th { color: #8E99AF; font-weight: 500; font-size: .75rem; text-transform: uppercase; }
code { background: #152344; padding: .125rem .375rem; border-radius: 3px; font-size: .875rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }
.thumb { background: #152344; padding: .5rem; border-radius: 6px; text-align: center; }
.thumb img { max-width: 100%; height: auto; border-radius: 4px; }
.thumb p { margin: .5rem 0 0; font-size: .75rem; color: #8E99AF; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin: 1rem 0; }
.metric { background: #152344; padding: 1rem; border-radius: 6px; text-align: center; }
.metric .num { font-size: 2rem; font-weight: 700; }
.metric .lbl { font-size: .75rem; color: #8E99AF; text-transform: uppercase; }
</style>
</head>
<body>
"""]

    html.append(f"<h1>AI Tester — Monitor KSeF</h1>")
    html.append(f"<p><code>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code></p>")

    # Pytest report link
    pytest_report = REPORTS / "report.html"
    if pytest_report.exists():
        html.append(f'<p><a href="report.html" style="color:#007AFF;">📊 Pelny raport pytest (HTML) →</a></p>')

    # Explorer summary
    html.append("<h2>🧭 AI Explorer</h2>")
    for label, data in [("Public (bez auth)", explorer_public), ("Authed (zalogowany)", explorer_authed)]:
        if not data:
            html.append(f"<div class='card'><h3>{label}</h3><p class='warn'>Brak danych — test nie uruchomiony.</p></div>")
            continue

        s = data.get("summary", {})
        html.append(f"<div class='card'><h3>{label}</h3>")
        html.append("<div class='summary-grid'>")
        for key, label_ in [
            ("total_visited", "Odwiedzone"),
            ("ok", "OK"),
            ("with_console_errors", "Console errors"),
            ("with_failed_requests", "Failed requests"),
            ("with_broken_images", "Broken images"),
            ("errored", "Crashe"),
        ]:
            val = s.get(key, 0)
            css = "ok" if val == 0 or key in ("total_visited", "ok") else ("err" if key == "errored" else "warn")
            html.append(f"<div class='metric'><div class='num {css}'>{val}</div><div class='lbl'>{label_}</div></div>")
        html.append("</div>")

        problematic = [
            p for p in data.get("pages", [])
            if p.get("status") != "ok" or p.get("console_errors") or p.get("error")
        ]
        if problematic:
            html.append("<h4>⚠️ Strony z problemami:</h4><table>")
            html.append("<tr><th>URL</th><th>Status</th><th>Console errors</th><th>Failed requests</th></tr>")
            for p in problematic:
                html.append(f"<tr><td><code>{p['url']}</code></td>")
                html.append(f"<td class='warn'>{p.get('status','-')}</td>")
                html.append(f"<td>{len(p.get('console_errors',[]))}</td>")
                html.append(f"<td>{len(p.get('failed_requests',[]))}</td></tr>")
            html.append("</table>")
        html.append("</div>")

    # Accessibility
    html.append("<h2>♿ Accessibility (axe-core)</h2>")
    if a11y_files:
        html.append("<table><tr><th>Strona</th><th>Violations</th><th>Critical</th></tr>")
        for f in a11y_files:
            data = load_json(f) or []
            critical = sum(1 for v in data if v.get("impact") == "critical")
            css = "ok" if not data else ("err" if critical else "warn")
            html.append(f"<tr><td><code>{f.stem.replace('a11y_', '')}</code></td>")
            html.append(f"<td class='{css}'>{len(data)}</td>")
            html.append(f"<td class='{'err' if critical else 'ok'}'>{critical}</td></tr>")
        html.append("</table>")
    else:
        html.append("<p class='warn'>Brak danych a11y.</p>")

    # Screenshots
    if screenshots:
        html.append("<h2>📸 Screenshoty</h2>")
        html.append("<div class='grid'>")
        for s in screenshots:
            rel = f"../screenshots/{s.name}"
            html.append(f"<div class='thumb'><a href='{rel}'><img src='{rel}' alt='{s.name}'></a><p>{s.name}</p></div>")
        html.append("</div>")

    html.append("</body></html>")
    return "".join(html)


def main():
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "ai_tester_report.html"
    out.write_text(render_html(), encoding="utf-8")
    print(f"\n✓ Raport: {out}")
    print(f"  Otworz: open {out}")


if __name__ == "__main__":
    main()
