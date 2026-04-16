"""Smoke tests for voxpact.Agent - uses mocks, no real HTTP."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from voxpact import Agent


@pytest.fixture
def patched_client():
    with patch("voxpact.agent.VoxpactClient") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


def test_agent_instantiation(patched_client):
    agent = Agent(name="translator", api_key="vp_live_test", owner_email="me@x.com")
    assert agent.name == "translator"
    assert agent.handlers == {}
    assert agent.poll_interval == 5.0


def test_job_decorator_registers_handler(patched_client):
    agent = Agent(name="translator", api_key="vp_live_test")

    @agent.job("translate", price_eur=5.0, description="Translate text")
    def translate(text: str, target_lang: str) -> str:
        return f"{text}->{target_lang}"

    assert "translate" in agent.handlers
    handler = agent.handlers["translate"]
    assert handler.price_eur == 5.0
    assert handler.description == "Translate text"
    assert handler.func is translate


def test_input_schema_introspection_types(patched_client):
    agent = Agent(name="t", api_key="vp_live_test")

    @agent.job("test", price_eur=1.0)
    def fn(s: str, i: int, f: float, b: bool, l: list, d: dict, x):
        return None

    schema = agent.handlers["test"].input_schema
    props = schema["properties"]
    assert props["s"]["type"] == "string"
    assert props["i"]["type"] == "integer"
    assert props["f"]["type"] == "number"
    assert props["b"]["type"] == "boolean"
    assert props["l"]["type"] == "array"
    assert props["d"]["type"] == "object"
    assert props["x"]["type"] == "string"  # no annotation -> string default


def test_required_vs_optional_params(patched_client):
    agent = Agent(name="t", api_key="vp_live_test")

    @agent.job("test", price_eur=1.0)
    def fn(required_arg: str, optional_arg: int = 5):
        return None

    schema = agent.handlers["test"].input_schema
    assert "required_arg" in schema["required"]
    assert "optional_arg" not in schema["required"]


def test_process_job_dispatches_to_handler(patched_client):
    agent = Agent(name="t", api_key="vp_live_test")
    captured = {}

    @agent.job("echo", price_eur=1.0)
    def echo(message: str) -> str:
        captured["called_with"] = message
        return f"echo:{message}"

    job = {"id": "job_123", "spec": {"name": "echo", "inputs": {"message": "hi"}}}
    agent._process_job(job)

    assert captured["called_with"] == "hi"
    patched_client.deliver_job.assert_called_once_with(
        "job_123", deliverable={"result": "echo:hi"}
    )


def test_process_job_unknown_name_logs_warning(patched_client, caplog):
    agent = Agent(name="t", api_key="vp_live_test")
    job = {"id": "job_456", "spec": {"name": "nonexistent", "inputs": {}}}

    with caplog.at_level(logging.WARNING):
        agent._process_job(job)

    patched_client.deliver_job.assert_not_called()
    assert any("No handler" in rec.message for rec in caplog.records)


def test_process_job_handler_exception_is_reported(patched_client):
    agent = Agent(name="t", api_key="vp_live_test")

    @agent.job("boom", price_eur=1.0)
    def boom() -> str:
        raise ValueError("kaboom")

    job = {"id": "job_789", "spec": {"name": "boom", "inputs": {}}}
    agent._process_job(job)

    patched_client.deliver_job.assert_called_once()
    call_args = patched_client.deliver_job.call_args
    assert call_args.args[0] == "job_789"
    deliverable = call_args.kwargs["deliverable"]
    assert "error" in deliverable
    assert "kaboom" in deliverable["error"]
    assert deliverable["handler"] == "boom"
