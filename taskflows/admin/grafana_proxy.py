"""Reverse proxy for Grafana.

Forwards requests to the local Grafana instance, injecting a service account
token for authentication. Grafana is bound to 127.0.0.1 only, so external
access must go through this proxy.
"""

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import Response

from taskflows.common import Config, logger

config = Config()

router = APIRouter(prefix="/grafana")

_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def grafana_proxy(path: str, request: Request):
    target_url = f"http://{config.grafana}/grafana/{path}"
    query_string = str(request.url.query)
    if query_string:
        target_url = f"{target_url}?{query_string}"

    headers = dict(request.headers)
    # Remove hop-by-hop headers
    for h in ("host", "connection", "transfer-encoding"):
        headers.pop(h, None)

    # Inject service account token
    if config.grafana_api_key:
        headers["Authorization"] = f"Bearer {config.grafana_api_key}"

    body = await request.body()

    session = await _get_session()
    try:
        async with session.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=body if body else None,
            allow_redirects=False,
        ) as resp:
            # Read full response
            content = await resp.read()

            # Build response headers, stripping hop-by-hop and X-Frame-Options
            response_headers = {}
            skip = {"transfer-encoding", "content-encoding", "content-length", "x-frame-options"}
            for key, value in resp.headers.items():
                if key.lower() not in skip:
                    response_headers[key] = value

            return Response(
                content=content,
                status_code=resp.status,
                headers=response_headers,
                media_type=resp.content_type,
            )
    except aiohttp.ClientError as e:
        logger.error(f"Grafana proxy error: {e}")
        return Response(
            content=f'{{"error": "Grafana unreachable: {e}"}}',
            status_code=502,
            media_type="application/json",
        )
