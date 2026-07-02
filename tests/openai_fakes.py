"""Shared fakes for mocking OpenAI chat.completions.create() responses in
tests, used by every LLM-backed service's test suite."""

import json
from dataclasses import dataclass


@dataclass
class FakeMessage:
    content: str | None = None
    refusal: str | None = None


@dataclass
class FakeChoice:
    message: FakeMessage
    finish_reason: str = "stop"


@dataclass
class FakeResponse:
    choices: list


def text_response(payload: dict) -> FakeResponse:
    return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=json.dumps(payload)))])


def raw_text_response(text: str) -> FakeResponse:
    return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=text))])


def refusal_response(reason: str = "정책 위반") -> FakeResponse:
    return FakeResponse(choices=[FakeChoice(message=FakeMessage(refusal=reason))])
