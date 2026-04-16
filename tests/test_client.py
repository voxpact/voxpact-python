"""Tests for VoxpactClient. Uses pytest-httpx to stub HTTP calls."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from voxpact import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    VoxpactClient,
    VoxpactError,
)

BASE = "https://api.voxpact.com"
API_KEY = "vp_live_test"
EMAIL = "test@example.com"


def _auth_stub(httpx_mock: HTTPXMock, token: str = "jwt-token") -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v1/agents/auth/token",
        json={"success": True, "data": {"token": token}},
    )


# ── Auth ────────────────────────────────────────────────────────────


def test_jwt_is_exchanged_on_first_authed_call(httpx_mock: HTTPXMock) -> None:
    _auth_stub(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/agents/me",
        json={"success": True, "data": {"id": "agent-1", "name": "bot"}},
    )

    with VoxpactClient(api_key=API_KEY, owner_email=EMAIL) as vp:
        me = vp.me()

    assert me["id"] == "agent-1"

    # Second call on /v1/agents/me should use the cached token (no extra auth call)
    auth_calls = [
        r for r in httpx_mock.get_requests() if r.url.path == "/v1/agents/auth/token"
    ]
    assert len(auth_calls) == 1


def test_preset_jwt_skips_token_exchange(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/agents/me",
        json={"success": True, "data": {"id": "agent-1"}},
    )

    with VoxpactClient(jwt="preset-jwt") as vp:
        vp.me()

    # No call should have been made to the token endpoint
    assert not any(
        r.url.path == "/v1/agents/auth/token" for r in httpx_mock.get_requests()
    )


def test_missing_credentials_raises(httpx_mock: HTTPXMock) -> None:
    with VoxpactClient() as vp:
        with pytest.raises(AuthenticationError):
            vp.me()


def test_401_triggers_jwt_refresh(httpx_mock: HTTPXMock) -> None:
    # First token exchange
    _auth_stub(httpx_mock, token="expired-jwt")
    # First /me call returns 401
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/agents/me",
        status_code=401,
        json={"error": "expired"},
    )
    # Second token exchange (refresh)
    _auth_stub(httpx_mock, token="fresh-jwt")
    # Retry succeeds
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/agents/me",
        json={"success": True, "data": {"id": "agent-1"}},
    )

    with VoxpactClient(api_key=API_KEY, owner_email=EMAIL) as vp:
        me = vp.me()

    assert me["id"] == "agent-1"


# ── Errors ──────────────────────────────────────────────────────────


def test_404_raises_not_found(httpx_mock: HTTPXMock) -> None:
    _auth_stub(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/jobs/missing",
        status_code=404,
        json={"error": "Job not found"},
    )

    with VoxpactClient(api_key=API_KEY, owner_email=EMAIL) as vp:
        with pytest.raises(NotFoundError):
            vp.get_job("missing")


def test_422_raises_validation(httpx_mock: HTTPXMock) -> None:
    _auth_stub(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v1/jobs",
        status_code=422,
        json={"error": "amount must be >= 5"},
    )

    with VoxpactClient(api_key=API_KEY, owner_email=EMAIL) as vp:
        with pytest.raises(ValidationError):
            vp.create_job(title="t", task_spec={}, amount=1.0)


def test_429_exposes_retry_after(httpx_mock: HTTPXMock) -> None:
    _auth_stub(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/agents/me",
        status_code=429,
        headers={"Retry-After": "7"},
        json={"error": "slow down"},
    )

    with VoxpactClient(api_key=API_KEY, owner_email=EMAIL) as vp:
        with pytest.raises(RateLimitError) as exc_info:
            vp.me()

    assert exc_info.value.retry_after == 7


def test_success_false_body_raises(httpx_mock: HTTPXMock) -> None:
    _auth_stub(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/agents/me",
        json={"success": False, "error": "something went wrong"},
    )

    with VoxpactClient(api_key=API_KEY, owner_email=EMAIL) as vp:
        with pytest.raises(VoxpactError):
            vp.me()


# ── Resource methods ────────────────────────────────────────────────


def test_register_agent_no_auth(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v1/agents/register",
        json={"success": True, "data": {"agent_id": "a-1", "state": "pending"}},
    )

    result = VoxpactClient.register_agent(
        name="bot",
        owner_email=EMAIL,
        owner_country="US",
        webhook_url="https://x.com/hook",
        capabilities=["writing"],
    )

    assert result["agent_id"] == "a-1"
    # Ensure no Authorization header was sent
    req = httpx_mock.get_requests()[0]
    assert "authorization" not in {k.lower() for k in req.headers.keys()}


def test_search_agents_returns_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/v1/agents/search?limit=20&q=translation",
        json={"success": True, "data": [{"id": "a-1"}, {"id": "a-2"}]},
    )

    with VoxpactClient() as vp:
        agents = vp.search_agents(query="translation")

    assert len(agents) == 2
    assert agents[0]["id"] == "a-1"


def test_create_job_sends_full_payload(httpx_mock: HTTPXMock) -> None:
    _auth_stub(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v1/jobs",
        json={"success": True, "data": {"id": "job-1"}},
        match_json={
            "title": "Translate",
            "task_spec": {"text": "hi", "target": "es"},
            "amount": 5.0,
            "job_type": "direct",
            "worker_agent_id": "worker-1",
        },
    )

    with VoxpactClient(api_key=API_KEY, owner_email=EMAIL) as vp:
        job = vp.create_job(
            title="Translate",
            task_spec={"text": "hi", "target": "es"},
            amount=5.0,
            worker_agent_id="worker-1",
        )

    assert job["id"] == "job-1"


def test_submit_review_validates_rating() -> None:
    with VoxpactClient(jwt="j") as vp:
        with pytest.raises(ValueError):
            vp.submit_review("job-1", rating=6)
        with pytest.raises(ValueError):
            vp.submit_review("job-1", rating=0)


def test_health_no_auth(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE}/health",
        json={"success": True, "data": {"status": "ok"}},
    )

    with VoxpactClient() as vp:
        h = vp.health()

    assert h["status"] == "ok"
