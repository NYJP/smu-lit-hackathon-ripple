"""Small OpenAI-compatible HTTP boundary used by extraction and retrieval."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from api import db
from api.errors import ApiError

_STATUS = "unconfigured"


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.total_tokens + other.total_tokens,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class ExternalServiceError(Exception):
    """The configured external endpoint rejected or could not serve a call."""


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


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    response = httpx.post(url, json=payload, headers=headers, timeout=60.0)
    response.raise_for_status()
    return response.json()


def _usage(payload: dict[str, Any]) -> Usage:
    usage = payload.get("usage") or {}
    return Usage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
    )


def _request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    global _STATUS
    key = require_configured()
    try:
        response = _post_json(
            f"{_base_url()}{path}", payload, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        _STATUS = "unreachable"
        raise ExternalServiceError("The configured model service could not be reached.") from exc
    _STATUS = "ok"
    return response


def structured_completion(system: str, user: str, schema: dict[str, Any]) -> tuple[dict[str, Any], Usage]:
    payload = _request(
        "/chat/completions",
        {
            "model": os.environ.get("RIPPLE_REASONING_MODEL", "gpt-5"),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "requirements", "strict": True, "schema": schema}},
            "max_completion_tokens": 12000,
        },
    )
    try:
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content), _usage(payload)
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ExternalServiceError("The configured model service returned an invalid extraction response.") from exc


def embed(texts: list[str]) -> tuple[list[list[float]], Usage]:
    if not texts:
        return [], Usage()
    vectors: list[list[float]] = []
    usage = Usage()
    for start in range(0, len(texts), 128):
        batch = texts[start:start + 128]
        payload = _request("/embeddings", {"model": os.environ.get("RIPPLE_EMBEDDING_MODEL", "text-embedding-3-small"), "input": batch})
        try:
            data = sorted(payload["data"], key=lambda row: row["index"])
            batch_vectors = [[float(value) for value in row["embedding"]] for row in data]
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalServiceError("The configured model service returned an invalid embedding response.") from exc
        if len(batch_vectors) != len(batch):
            raise ExternalServiceError("The configured model service returned an incomplete embedding response.")
        for vector in batch_vectors:
            if len(vector) != db.EMBEDDING_DIMS:
                raise ExternalServiceError(
                    f"Embedding dimensionality mismatch: expected {db.EMBEDDING_DIMS} values. Run 'python scripts/reindex.py --dims {len(vector)}'."
                )
        vectors.extend(batch_vectors)
        usage = usage.add(_usage(payload))
    return vectors, usage
