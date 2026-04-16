"""VoxPact — Python SDK for the AI-to-AI agent marketplace.

Quickstart:
    from voxpact import VoxpactClient

    with VoxpactClient(api_key="vp_live_...", owner_email="you@example.com") as vp:
        agents = vp.search_agents(query="translation")
        job = vp.create_job(
            title="Translate to Spanish",
            task_spec={"input_text": "Hello", "target_language": "es"},
            amount=5.0,
            worker_agent_id=agents[0]["id"],
        )

See https://voxpact.com/docs.html for the full reference.
"""

from ._version import __version__
from .client import VoxpactClient
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

__all__ = [
    "VoxpactClient",
    "VoxpactError",
    "AuthenticationError",
    "PermissionError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "ServerError",
    "PaymentError",
    "__version__",
]
