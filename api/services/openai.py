"""Resilient official OpenAI SDK boundary for extraction and retrieval."""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

import jsonschema
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from api import db
from api.errors import ApiError
from api.services import usage as usage_costs

T = TypeVar("T")
_STATUS = "unconfigured"
_CLIENT: OpenAI | None = None
_CLIENT_KEY: tuple[str, str] | None = None
_CLIENT_LOCK = threading.Lock()
_SEMAPHORE: threading.BoundedSemaphore | None = None
_SEMAPHORE_SIZE: int | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = 0.0

    def add(self, other: "Usage") -> "Usage":
        cost = (
            None
            if self.estimated_cost_usd is None or other.estimated_cost_usd is None
            else self.estimated_cost_usd + other.estimated_cost_usd
        )
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.total_tokens + other.total_tokens,
            cost,
        )

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


@dataclass(frozen=True)
class OpenAIResult(Generic[T]):
    value: T
    raw_response: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float | None
    model: str

    @property
    def usage(self) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.prompt_tokens + self.completion_tokens,
            estimated_cost_usd=self.estimated_cost_usd,
        )


class ExternalServiceError(ApiError):
    """The configured external endpoint rejected or could not serve a call."""

    def __init__(self, message: str, *, raw_response: dict[str, Any] | None = None):
        super().__init__(502, "external_service_error", message, {"retryable": True})
        self.raw_response = raw_response


def require_configured() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ApiError(503, "unavailable", "OPENAI_API_KEY is required for retrieval.")
    return key


def status() -> str:
    if not os.environ.get("OPENAI_API_KEY"):
        return "unconfigured"
    return _STATUS if _STATUS != "unconfigured" else "configured"


def _base_url() -> str:
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _client() -> OpenAI:
    global _CLIENT, _CLIENT_KEY
    key = require_configured()
    identity = (key, _base_url())
    with _CLIENT_LOCK:
        if _CLIENT is None or _CLIENT_KEY != identity:
            _CLIENT = OpenAI(api_key=key, base_url=identity[1], timeout=60.0, max_retries=0)
            _CLIENT_KEY = identity
        return _CLIENT


def _semaphore() -> threading.BoundedSemaphore:
    global _SEMAPHORE, _SEMAPHORE_SIZE
    try:
        size = max(1, int(os.environ.get("OPENAI_MAX_CONCURRENCY", "4")))
    except ValueError:
        size = 4
    with _CLIENT_LOCK:
        if _SEMAPHORE is None or _SEMAPHORE_SIZE != size:
            _SEMAPHORE = threading.BoundedSemaphore(size)
            _SEMAPHORE_SIZE = size
        return _SEMAPHORE


def _call_with_retries(call: Callable[[], T]) -> T:
    global _STATUS
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with _semaphore():
                result = call()
            _STATUS = "ok"
            return result
        except APIStatusError as exc:
            last_error = exc
            if exc.status_code != 429 and exc.status_code < 500:
                break
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep((0.5 * (2**attempt)) + random.uniform(0, 0.2))
    _STATUS = "unreachable"
    raise ExternalServiceError("The configured model service could not be reached.") from last_error


def _response_dict(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    return json.loads(response.model_dump_json())


def _record_schema_failure(
    conn: Any,
    job_id: str | None,
    raw_response: dict[str, Any],
    validation_error: str,
) -> None:
    if conn is None or not job_id:
        return
    from api.services import jobs

    jobs.append_error_context(
        conn,
        job_id,
        {"kind": "structured_output", "validation_error": validation_error, "response": raw_response},
    )


def structured_completion(
    system: str,
    user: str,
    schema: dict[str, Any],
    *,
    model: str | None = None,
    schema_name: str = "requirements",
    job_conn: Any = None,
    job_id: str | None = None,
) -> OpenAIResult[dict[str, Any]]:
    selected_model = model or os.environ.get("RIPPLE_REASONING_MODEL", "gpt-5")
    repair = ""
    last_raw: dict[str, Any] | None = None
    raw_attempts: list[dict[str, Any]] = []
    prompt_tokens = 0
    completion_tokens = 0
    for schema_attempt in range(2):
        response = _call_with_retries(
            lambda: _client().chat.completions.create(
                model=selected_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + repair},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
                max_completion_tokens=12000,
            )
        )
        raw = _response_dict(response)
        last_raw = raw
        raw_attempts.append(raw)
        response_usage = response.usage
        prompt_tokens += int(response_usage.prompt_tokens if response_usage else 0)
        completion_tokens += int(response_usage.completion_tokens if response_usage else 0)
        try:
            content = response.choices[0].message.content
            if not content:
                raise ValueError("The response content was empty.")
            value = json.loads(content)
            jsonschema.validate(value, schema)
        except (IndexError, TypeError, ValueError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            _record_schema_failure(job_conn, job_id, raw, str(exc))
            if schema_attempt == 0:
                repair = (
                    "\n\nYour previous response failed validation. Return a complete replacement "
                    f"that strictly matches the supplied schema. Validation error: {exc}"
                )
                continue
            raise ExternalServiceError(
                "The configured model service returned invalid structured output.",
                raw_response=raw,
            ) from exc
        return OpenAIResult(
            value=value,
            raw_response={"attempts": raw_attempts},
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=usage_costs.estimate_cost(selected_model, prompt_tokens, completion_tokens),
            model=selected_model,
        )
    raise ExternalServiceError(
        "The configured model service returned invalid structured output.",
        raw_response=last_raw,
    )


def embed(texts: list[str]) -> OpenAIResult[list[list[float]]]:
    selected_model = os.environ.get("RIPPLE_EMBEDDING_MODEL", "text-embedding-3-small")
    if not texts:
        return OpenAIResult([], {}, 0, 0, 0.0, selected_model)
    vectors: list[list[float]] = []
    raw_batches: list[dict[str, Any]] = []
    prompt_tokens = 0
    for start in range(0, len(texts), 128):
        batch = texts[start:start + 128]
        response = _call_with_retries(
            lambda batch=batch: _client().embeddings.create(model=selected_model, input=batch)
        )
        raw_batches.append(_response_dict(response))
        try:
            data = sorted(response.data, key=lambda row: row.index)
            batch_vectors = [[float(value) for value in row.embedding] for row in data]
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExternalServiceError(
                "The configured model service returned an invalid embedding response.",
                raw_response=raw_batches[-1],
            ) from exc
        if len(batch_vectors) != len(batch):
            raise ExternalServiceError("The configured model service returned an incomplete embedding response.")
        for vector in batch_vectors:
            if len(vector) != db.EMBEDDING_DIMS:
                raise ExternalServiceError(
                    f"Embedding dimensionality mismatch: detected {len(vector)}, expected {db.EMBEDDING_DIMS}. "
                    f"Run 'python run.py reindex --dimensions {len(vector)}'."
                )
        vectors.extend(batch_vectors)
        if response.usage:
            prompt_tokens += int(response.usage.prompt_tokens)
    return OpenAIResult(
        value=vectors,
        raw_response={"batches": raw_batches},
        prompt_tokens=prompt_tokens,
        completion_tokens=0,
        estimated_cost_usd=usage_costs.estimate_cost(selected_model, prompt_tokens, 0),
        model=selected_model,
    )
