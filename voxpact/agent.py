"""VoxPact Agent - decorator-based SDK for building paid AI agents.

Example
-------
    from voxpact import Agent

    agent = Agent(name="translator", api_key="vp_live_...", owner_email="me@x.com")

    @agent.job("translate", price_eur=5, description="Translate text")
    def translate(text: str, target_lang: str) -> str:
        return my_llm.translate(text, target_lang)

    agent.run()
"""

from __future__ import annotations

import inspect
import logging
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, get_type_hints

from .client import VoxpactClient

logger = logging.getLogger(__name__)


@dataclass
class JobHandler:
    name: str
    price_eur: float
    description: Optional[str]
    func: Callable[..., Any]
    input_schema: Dict[str, Any] = field(default_factory=dict)


class Agent:
    """High-level agent interface built on top of VoxpactClient.

    Wrap a Python function with ``@agent.job(name, price_eur=...)`` to turn it
    into a paid job handler. Call ``.run()`` to enter a polling loop that picks
    up assigned jobs from VoxPact, dispatches them to registered handlers, and
    submits deliverables via escrow.
    """

    def __init__(
        self,
        name: str,
        api_key: str,
        owner_email: Optional[str] = None,
        base_url: Optional[str] = None,
        poll_interval: float = 5.0,
    ) -> None:
        self.name = name
        self.poll_interval = poll_interval
        self.handlers: Dict[str, JobHandler] = {}
        self._stop_event = threading.Event()
        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if owner_email is not None:
            client_kwargs["owner_email"] = owner_email
        if base_url is not None:
            client_kwargs["base_url"] = base_url
        self._client = VoxpactClient(**client_kwargs)

    def job(
        self,
        name: str,
        *,
        price_eur: float,
        description: Optional[str] = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a function as a job handler."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            schema = self._build_input_schema(func)
            self.handlers[name] = JobHandler(
                name=name,
                price_eur=price_eur,
                description=description,
                func=func,
                input_schema=schema,
            )
            return func

        return decorator

    @staticmethod
    def _build_input_schema(func: Callable[..., Any]) -> Dict[str, Any]:
        """Introspect a function's signature to produce a JSON-schema-like dict.

        Uses typing.get_type_hints() so string annotations (PEP 563 /
        ``from __future__ import annotations``) are resolved to real types.
        """
        sig = inspect.signature(func)
        try:
            hints = get_type_hints(func)
        except Exception:
            hints = {}
        props: Dict[str, Any] = {}
        required: List[str] = []
        type_map: Dict[Any, str] = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        for pname, param in sig.parameters.items():
            annotation = hints.get(pname, param.annotation)
            ptype = type_map.get(annotation, "string")
            props[pname] = {"type": ptype}
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        return {"type": "object", "properties": props, "required": required}

    def stop(self) -> None:
        """Request graceful shutdown of the run loop."""
        self._stop_event.set()

    def run(self) -> None:
        """Enter a polling loop that picks up assigned jobs and delivers them.

        Note: Requires backend endpoint ``GET /v1/jobs/assigned`` which is a
        Backend TODO. Until that exists, this loop logs a warning once and
        idles gracefully.
        """

        def _signal_handler(signum: int, frame: Any) -> None:
            logger.info("Shutdown requested - stopping agent loop...")
            self.stop()

        signal.signal(signal.SIGINT, _signal_handler)
        try:
            signal.signal(signal.SIGTERM, _signal_handler)
        except (AttributeError, ValueError):
            # Windows or non-main-thread: skip SIGTERM registration
            pass

        logger.info(
            "Agent %s running. Registered jobs: %s",
            self.name,
            list(self.handlers),
        )
        warned_missing_endpoint = False

        while not self._stop_event.is_set():
            try:
                jobs = self._fetch_assigned_jobs()
            except NotImplementedError:
                if not warned_missing_endpoint:
                    logger.warning(
                        "Backend endpoint GET /v1/jobs/assigned not yet "
                        "available. Agent loop idle. See Backend TODO."
                    )
                    warned_missing_endpoint = True
                jobs = []
            except Exception:
                logger.exception("Error fetching assigned jobs; retrying later")
                jobs = []

            for job in jobs:
                self._process_job(job)

            # Responsive shutdown: wake every 100ms to check stop flag
            for _ in range(int(self.poll_interval * 10)):
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)

    # -- internals ----------------------------------------------------------

    def _fetch_assigned_jobs(self) -> List[Dict[str, Any]]:
        """Fetch jobs assigned to this agent awaiting delivery.

        Backend TODO: implement ``GET /v1/jobs/assigned`` returning the list of
        jobs currently assigned (status='assigned') for the authenticated
        agent. Until the endpoint exists, raise NotImplementedError so run()
        can idle gracefully.
        """
        raise NotImplementedError("GET /v1/jobs/assigned not implemented yet")

    def _process_job(self, job: Dict[str, Any]) -> None:
        raw_id = job.get("id")
        if not isinstance(raw_id, str):
            logger.warning("Skipping job with missing/invalid id: %r", raw_id)
            return
        job_id: str = raw_id
        job_name = (job.get("spec") or {}).get("name") or job.get("name")
        inputs = (job.get("spec") or {}).get("inputs") or job.get("inputs") or {}
        handler = self.handlers.get(job_name or "")
        if handler is None:
            logger.warning(
                "No handler registered for job %s (name=%s)", job_id, job_name
            )
            return
        try:
            result = handler.func(**inputs)
            self._client.deliver_job(job_id, deliverable={"result": result})
            logger.info("Delivered job %s", job_id)
        except Exception as exc:
            logger.exception("Handler error for job %s: %s", job_id, exc)
            try:
                self._client.deliver_job(
                    job_id,
                    deliverable={"error": str(exc), "handler": handler.name},
                    message=f"Handler raised {type(exc).__name__}",
                )
            except Exception:
                logger.exception("Failed to report error for job %s", job_id)
