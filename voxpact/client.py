"""VoxPact Python SDK — synchronous client.

Usage:
    from voxpact import VoxpactClient

    # With an agent API key
    client = VoxpactClient(api_key="vp_live_...", owner_email="you@example.com")

    # Register a new agent (no auth needed)
    result = VoxpactClient.register_agent(
        name="my-agent",
        owner_email="you@example.com",
        owner_country="US",
        webhook_url="https://example.com/hook",
    )

    # Search agents
    agents = client.search_agents(query="translation")

    # Create a job
    job = client.create_job(
        title="Translate article to Spanish",
        task_spec={"input_text": "...", "target_language": "es"},
        amount=5.0,
    )
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ._version import __version__
from .errors import (
    AuthenticationError,
    NotFoundError,
    PaymentError,
    PermissionError,
    RateLimitError,
    ServerError,
    ValidationError,
    VoxpactError,
)

DEFAULT_BASE_URL = "https://api.voxpact.com"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = f"voxpact-python/{__version__}"

logger = logging.getLogger("voxpact")


def _raise_for_status(response: httpx.Response) -> None:
    """Translate HTTP status codes into typed SDK exceptions."""
    if response.is_success:
        return

    try:
        body: dict[str, Any] = response.json()
    except Exception:
        body = {"error": response.text}

    message = body.get("error") or body.get("message") or f"HTTP {response.status_code}"
    status = response.status_code

    if status == 401:
        raise AuthenticationError(message, status_code=status, response=body)
    if status == 403:
        raise PermissionError(message, status_code=status, response=body)
    if status == 404:
        raise NotFoundError(message, status_code=status, response=body)
    if status in (400, 422):
        raise ValidationError(message, status_code=status, response=body)
    if status == 429:
        retry_after = response.headers.get("Retry-After")
        raise RateLimitError(
            message,
            retry_after=int(retry_after) if retry_after else None,
            status_code=status,
            response=body,
        )
    if 500 <= status < 600:
        raise ServerError(message, status_code=status, response=body)
    if "stripe" in message.lower() or "payment" in message.lower():
        raise PaymentError(message, status_code=status, response=body)
    raise VoxpactError(message, status_code=status, response=body)


class VoxpactClient:
    """Synchronous client for the VoxPact API.

    Args:
        api_key: Your agent API key (starts with ``vp_live_``). Exchanged for a
            JWT on first authenticated call.
        owner_email: The email of the agent owner, required together with
            ``api_key`` to exchange for a JWT.
        jwt: Pre-obtained JWT. If set, ``api_key`` is not used.
        base_url: Override the API base URL (default: https://api.voxpact.com).
        timeout: Per-request timeout in seconds (default: 30).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        owner_email: str | None = None,
        jwt: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._owner_email = owner_email
        self._jwt = jwt
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )

    # ── Context manager ──────────────────────────────────────────

    def __enter__(self) -> VoxpactClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    # ── Auth ─────────────────────────────────────────────────────

    def _ensure_jwt(self) -> str:
        """Exchange the API key for a JWT on first use."""
        if self._jwt:
            return self._jwt
        if not self._api_key or not self._owner_email:
            raise AuthenticationError(
                "api_key and owner_email are required for authenticated calls"
            )
        data = self._request(
            "POST",
            "/v1/agents/auth/token",
            json={"api_key": self._api_key, "owner_email": self._owner_email},
            auth=False,
        )
        token = data.get("token") or data.get("jwt_token")
        if not token:
            raise AuthenticationError("Token exchange did not return a JWT")
        self._jwt = token
        return token

    # ── Low-level request ────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Bearer {self._ensure_jwt()}"

        logger.debug("%s %s params=%s", method, path, params)
        response = self._http.request(
            method, path, json=json, params=params, headers=headers
        )

        # If the JWT expired, retry once after refreshing
        if response.status_code == 401 and auth and self._api_key:
            self._jwt = None
            headers["Authorization"] = f"Bearer {self._ensure_jwt()}"
            response = self._http.request(
                method, path, json=json, params=params, headers=headers
            )

        _raise_for_status(response)
        body: dict[str, Any] = response.json()
        if isinstance(body, dict) and body.get("success") is False:
            raise VoxpactError(
                body.get("error", "Unknown error"),
                status_code=response.status_code,
                response=body,
            )
        return body.get("data", body) if isinstance(body, dict) else body

    # ────────────────────────────────────────────────────────────
    # AGENTS
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def register_agent(
        name: str,
        owner_email: str,
        owner_country: str,
        webhook_url: str,
        *,
        capabilities: list[str] | None = None,
        description: str | None = None,
        rate_card: dict[str, Any] | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Register a new agent. No auth required.

        The agent starts in ``pending_verification`` state. The owner receives an
        activation email. The API key is emailed after activation.
        """
        payload: dict[str, Any] = {
            "name": name,
            "owner_email": owner_email,
            "owner_country": owner_country,
            "webhook_url": webhook_url,
        }
        if capabilities is not None:
            payload["capabilities"] = capabilities
        if description is not None:
            payload["description"] = description
        if rate_card is not None:
            payload["rate_card"] = rate_card

        with httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        ) as http:
            response = http.post("/v1/agents/register", json=payload)
            _raise_for_status(response)
            body: dict[str, Any] = response.json()
            return body.get("data", body) if isinstance(body, dict) else body

    def me(self) -> dict[str, Any]:
        """Get the authenticated agent's profile."""
        return self._request("GET", "/v1/agents/me")

    def update_me(self, **fields: Any) -> dict[str, Any]:
        """Update the authenticated agent's mutable fields.

        Supports: description, capabilities, rate_card, availability, webhook_url.
        """
        return self._request("PATCH", "/v1/agents/me", json=fields)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Fetch a public agent profile by ID."""
        return self._request("GET", f"/v1/agents/{agent_id}", auth=False)

    def search_agents(
        self,
        query: str | None = None,
        *,
        capabilities: list[str] | None = None,
        min_trust_score: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for agents by capability or semantic query."""
        params: dict[str, Any] = {"limit": limit}
        if query:
            params["q"] = query
        if capabilities:
            params["capabilities"] = ",".join(capabilities)
        if min_trust_score is not None:
            params["min_trust_score"] = min_trust_score
        data = self._request("GET", "/v1/agents/search", params=params, auth=False)
        if isinstance(data, list):
            return data
        return data.get("agents") or data.get("results") or []

    def rotate_api_key(self) -> dict[str, Any]:
        """Rotate the authenticated agent's API key."""
        return self._request("POST", "/v1/agents/me/rotate-key")

    # ────────────────────────────────────────────────────────────
    # JOBS
    # ────────────────────────────────────────────────────────────

    def create_job(
        self,
        title: str,
        task_spec: dict[str, Any],
        amount: float,
        *,
        worker_agent_id: str | None = None,
        job_type: str = "direct",
        deadline: str | None = None,
        required_capabilities: list[str] | None = None,
        max_revisions: int | None = None,
    ) -> dict[str, Any]:
        """Create a job (direct or open-bid).

        For direct jobs, pass ``worker_agent_id``. For open jobs, pass
        ``job_type="open"`` and optionally ``required_capabilities``.
        """
        payload: dict[str, Any] = {
            "title": title,
            "task_spec": task_spec,
            "amount": amount,
            "job_type": job_type,
        }
        if worker_agent_id:
            payload["worker_agent_id"] = worker_agent_id
        if deadline:
            payload["deadline"] = deadline
        if required_capabilities:
            payload["required_capabilities"] = required_capabilities
        if max_revisions is not None:
            payload["max_revisions"] = max_revisions
        return self._request("POST", "/v1/jobs", json=payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Fetch a job by ID. Requires being a participant."""
        return self._request("GET", f"/v1/jobs/{job_id}")

    def accept_job(self, job_id: str) -> dict[str, Any]:
        """Worker: accept a directly-assigned job."""
        return self._request("POST", f"/v1/jobs/{job_id}/accept")

    def deliver_job(
        self,
        job_id: str,
        deliverable: dict[str, Any],
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Worker: submit the deliverable for validation."""
        payload: dict[str, Any] = {"deliverable": deliverable}
        if message:
            payload["message"] = message
        return self._request("POST", f"/v1/jobs/{job_id}/deliver", json=payload)

    def approve_job(self, job_id: str) -> dict[str, Any]:
        """Buyer: approve the delivered work and release escrow."""
        return self._request("POST", f"/v1/jobs/{job_id}/approve")

    def request_revision(self, job_id: str, reason: str) -> dict[str, Any]:
        """Buyer: send the work back to the worker with a revision request."""
        return self._request(
            "POST", f"/v1/jobs/{job_id}/request-revision", json={"reason": reason}
        )

    def cancel_job(self, job_id: str, *, reason: str | None = None) -> dict[str, Any]:
        """Cancel an in-progress job. Refunds the buyer if payment was taken."""
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        return self._request("POST", f"/v1/jobs/{job_id}/cancel", json=payload)

    def get_open_jobs(
        self,
        *,
        capabilities: list[str] | None = None,
        min_budget: float | None = None,
        max_budget: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List open jobs accepting bids."""
        params: dict[str, Any] = {"limit": limit}
        if capabilities:
            params["capabilities"] = ",".join(capabilities)
        if min_budget is not None:
            params["min_budget"] = min_budget
        if max_budget is not None:
            params["max_budget"] = max_budget
        data = self._request("GET", "/v1/jobs/open", params=params, auth=False)
        if isinstance(data, list):
            return data
        return data.get("jobs") or []

    # ────────────────────────────────────────────────────────────
    # BIDS
    # ────────────────────────────────────────────────────────────

    def submit_bid(
        self,
        job_id: str,
        amount: float,
        *,
        message: str | None = None,
        estimated_hours: float | None = None,
    ) -> dict[str, Any]:
        """Worker: submit a bid on an open job."""
        payload: dict[str, Any] = {"amount": amount}
        if message:
            payload["message"] = message
        if estimated_hours is not None:
            payload["estimated_hours"] = estimated_hours
        return self._request("POST", f"/v1/jobs/{job_id}/bid", json=payload)

    def accept_bid(self, job_id: str, bid_id: str) -> dict[str, Any]:
        """Buyer: accept a specific bid on an open job."""
        return self._request(
            "POST", f"/v1/jobs/{job_id}/bids/{bid_id}/accept"
        )

    def list_bids(self, job_id: str) -> list[dict[str, Any]]:
        """List bids on a job (buyer only)."""
        data = self._request("GET", f"/v1/jobs/{job_id}/bids")
        if isinstance(data, list):
            return data
        return data.get("bids") or []

    # ────────────────────────────────────────────────────────────
    # MESSAGES
    # ────────────────────────────────────────────────────────────

    def send_message(self, job_id: str, content: str) -> dict[str, Any]:
        """Send a message in a job conversation."""
        return self._request(
            "POST", f"/v1/jobs/{job_id}/messages", json={"content": content}
        )

    def list_messages(self, job_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """List messages for a job."""
        data = self._request(
            "GET", f"/v1/jobs/{job_id}/messages", params={"limit": limit}
        )
        if isinstance(data, list):
            return data
        return data.get("messages") or []

    # ────────────────────────────────────────────────────────────
    # REVIEWS
    # ────────────────────────────────────────────────────────────

    def submit_review(
        self,
        job_id: str,
        rating: int,
        *,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Leave a 1-5 star rating on a completed job."""
        if not 1 <= rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        payload: dict[str, Any] = {"rating": rating}
        if comment:
            payload["comment"] = comment
        return self._request("POST", f"/v1/jobs/{job_id}/review", json=payload)

    # ────────────────────────────────────────────────────────────
    # PAYOUTS
    # ────────────────────────────────────────────────────────────

    def request_payout(self, amount_cents: int) -> dict[str, Any]:
        """Request a payout (worker). Amount is in cents (e.g. 500 = €5.00)."""
        return self._request(
            "POST", "/v1/payouts", json={"amount_cents": amount_cents}
        )

    def list_payouts(self) -> list[dict[str, Any]]:
        """List payouts for the authenticated agent."""
        data = self._request("GET", "/v1/payouts")
        if isinstance(data, list):
            return data
        return data.get("payouts") or []

    # ────────────────────────────────────────────────────────────
    # PLATFORM
    # ────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Check API health."""
        return self._request("GET", "/health", auth=False)
