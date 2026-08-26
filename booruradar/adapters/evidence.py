from __future__ import annotations

from hashlib import sha256

import httpx
from pydantic import BaseModel, ConfigDict, Field


class ResponseEvidence(BaseModel):
    """Bounded evidence about one response, without retaining its payload."""

    model_config = ConfigDict(frozen=True)

    endpoint_identifier: str = Field(min_length=1, max_length=100)
    http_status: int = Field(ge=100, le=599)
    content_type: str | None = Field(default=None, max_length=200)
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def fingerprint_response(response: httpx.Response, endpoint_identifier: str) -> ResponseEvidence:
    content_type = response.headers.get("content-type")
    return ResponseEvidence(
        endpoint_identifier=endpoint_identifier,
        http_status=response.status_code,
        content_type=content_type[:200] if content_type else None,
        response_sha256=sha256(response.content).hexdigest(),
    )
