"""
REST metrics must use route templates (bounded label set, no invoice numbers),
and the login/setup pages' static assets must load without a session.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import create_app

TOKEN = "x" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def seen_labels():
    return []


@pytest.fixture
def client(seen_labels):
    metrics = MagicMock()
    metrics.rest_api_requests_total.labels.side_effect = (
        lambda **kw: seen_labels.append(kw) or MagicMock()
    )
    return TestClient(create_app(db=None, auth_token=TOKEN, prometheus_metrics=metrics))


def test_metrics_label_is_route_template(client, seen_labels):
    client.get("/api/v1/invoices/1234567890-20260101-ABCDEF-12", headers=AUTH)
    assert seen_labels[-1]["endpoint"] == "/api/v1/invoices/{ksef_number}"


def test_metrics_label_unmatched_for_unknown_paths(client, seen_labels):
    for i in range(5):
        client.get(f"/random/{i}")
    assert {kw["endpoint"] for kw in seen_labels} == {"unmatched"}


def test_metrics_label_for_health(client, seen_labels):
    client.get("/api/v1/monitor/health")
    assert seen_labels[-1]["endpoint"] == "/api/v1/monitor/health"


@pytest.mark.parametrize("asset", ["tailwind.min.css", "favicon.png", "icon-64.png"])
def test_static_assets_public(client, asset):
    r = client.get(f"/ui/static/{asset}", follow_redirects=False)
    assert r.status_code == 200


def test_static_traversal_not_exposed(client):
    r = client.get("/ui/static/../templates/login.html", follow_redirects=False)
    assert r.status_code in (303, 401, 404)
    r = client.get("/ui/static/%2e%2e/templates/login.html", follow_redirects=False)
    assert r.status_code in (303, 401, 404)


def test_ui_still_requires_session(client):
    r = client.get("/ui", follow_redirects=False)
    assert r.status_code == 303
