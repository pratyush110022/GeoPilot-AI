from __future__ import annotations

import os
from typing import Any

import httpx


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() not in {"0", "false", "no", "off"}


VERIFY_SSL = _env_bool("GEO_HTTP_VERIFY_SSL", True)
ALLOW_INSECURE_FALLBACK = _env_bool("GEO_HTTP_ALLOW_INSECURE_FALLBACK", True)


def _is_cert_error(exc: Exception) -> bool:
    text = str(exc).upper()
    return "CERTIFICATE_VERIFY_FAILED" in text or "CERTIFICATE_VERIFY" in text


async def request(
    method: str,
    url: str,
    *,
    timeout: httpx.Timeout | float,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request with an opt-in local certificate fallback.

    Verification remains enabled by default. When a local/corporate CA is
    missing and the TLS handshake fails specifically with a certificate error,
    the request can retry once with verification disabled when
    GEO_HTTP_ALLOW_INSECURE_FALLBACK=true. This is intended for local
    development environments, not production.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=VERIFY_SSL, headers=headers) as client:
            return await client.request(method, url, **kwargs)
    except (httpx.ConnectError, httpx.TransportError) as exc:
        if not (VERIFY_SSL and ALLOW_INSECURE_FALLBACK and _is_cert_error(exc)):
            raise
        async with httpx.AsyncClient(timeout=timeout, verify=False, headers=headers) as client:
            return await client.request(method, url, **kwargs)
