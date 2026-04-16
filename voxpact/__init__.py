"""VoxPact - Payments SDK for AI agents.

Quickstart:
    from voxpact import Agent

    agent = Agent(name="translator", api_key="vp_live_...", owner_email="you@example.com")

    @agent.job("translate", price_eur=5)
    def translate(text: str, target_lang: str) -> str:
        return my_llm.translate(text, target_lang)

    agent.run()

See https://voxpact.com/docs.html for the full reference.
"""

from ._version import __version__
from .agent import Agent
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
    "Agent",
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
