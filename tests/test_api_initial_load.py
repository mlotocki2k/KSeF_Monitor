"""
Tests for initial-load API router — validation layer only.
"""


def test_initial_load_rejects_range_over_5y():
    """V5-11: reject start→end range > 5 years."""
    from fastapi.testclient import TestClient
    from app.api import create_app

    app = create_app(auth_token="a" * 32)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/initial-load/start",
        json={
            "start_date": "2019-01-01",
            "end_date": "2026-01-01",
            "subject_types": ["Subject1"],
        },
        headers={"Authorization": "Bearer " + "a" * 32},
    )
    assert resp.status_code == 422
    body = resp.json()
    # Pydantic surfaces model_validator errors as "value_error" in detail
    detail_str = str(body.get("detail", ""))
    assert "5 years" in detail_str or "1826" in detail_str


def test_initial_load_accepts_range_under_5y():
    """V5-11: accept ranges within 5 years (Pydantic passes, endpoint may 503)."""
    from fastapi.testclient import TestClient
    from app.api import create_app

    app = create_app(auth_token="a" * 32)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/initial-load/start",
        json={
            "start_date": "2022-01-01",
            "end_date": "2024-01-01",
            "subject_types": ["Subject1"],
        },
        headers={"Authorization": "Bearer " + "a" * 32},
    )
    # 503 means Pydantic validation passed and the router processed the request
    # (no InitialLoadManager configured in test app)
    assert resp.status_code != 422
