import json
import socket
from datetime import datetime, timezone
from functools import cache
from typing import Dict, Optional

import requests
import sqlalchemy as sa
from taskflows.common import logger
from taskflows.db import engine, get_tasks_db, servers_table

from .security import (create_hmac_headers,  # new import reuse
                       load_security_config, security_config)


@cache
def get_public_ipv4() -> Optional[str]:
    """Detect and cache the machine's public IPv4 address.

    Tries multiple external services and returns the first validated public IPv4.
    Cached for process lifetime; call get_public_ipv4.cache_clear() if refresh needed.
    """
    services = (
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://checkip.amazonaws.com",
    )
    for url in services:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                logger.debug(f"get_public_ipv4: Non-200 from {url}: {resp.status_code}")
                continue
            # Some services may return with newline; split to be safe
            candidate = resp.text.strip().split()[0]
            logger.debug(f"get_public_ipv4: Selected public IP {candidate} from {url}")
            return candidate
        except requests.RequestException as e:
            logger.debug(f"get_public_ipv4: Request error from {url}: {e}")
        except Exception as e:
            logger.debug(f"get_public_ipv4: Unexpected error from {url}: {e}")
    logger.warning("get_public_ipv4: Failed to determine public IPv4 address")
    return None

async def list_servers() -> list[dict]:
    """Get all servers from the database.
    
    Returns:
        List of server dictionaries with address and hostname fields
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(servers_table).order_by(servers_table.c.hostname)
        )
        results = [dict(row._mapping) for row in result]
    # Convert to expected format with 'address' field
    return [
        {"address": f"{s['public_ipv4']}:7777", "hostname": s["hostname"]}
        for s in results
    ]
    
async def upsert_server(
    hostname: Optional[str] = None, public_ipv4: Optional[str] = None
) -> None:
    """Upsert server information to the database.
    
    Args:
        hostname: Server hostname, defaults to current machine hostname
        public_ipv4: Server public IP, defaults to detected IP
    """
    if hostname is None:
        hostname = socket.gethostname()
    if public_ipv4 is None:
        public_ipv4 = get_public_ipv4()

    db = await get_tasks_db()
    await db.upsert(
        servers_table,
        hostname=hostname,
        public_ipv4=public_ipv4,
        last_updated=datetime.now(timezone.utc),
    )
    logger.info(f"Updated server info: hostname={hostname}, public_ipv4={public_ipv4}")


def get_server_api_url(server) -> str:
    """Return normalized base URL for a server.
    
    Args:
        server: Either a server dict with 'address' field or a plain string
        
    Returns:
        Normalized HTTP URL for the server
    """
    if isinstance(server, str):
        address = server
    else:
        address = server["address"]
    if not address.startswith("http"):
        address = f"http://{address}"
    if address.endswith("/"):
        address = address[:-1]
    return address


def _format_error_body(resp):
    """Return a pretty, size-limited string for an error HTTP response body.
    - Pretty prints JSON (indent=2)
    - Truncates very long tracebacks
    - Truncates overall payload to avoid log spam
    """
    try:
        text = resp.text or ""
    except Exception:
        return "<unreadable body>"
    if not text:
        return "<empty body>"
    # Cap total size in logs
    MAX_TOTAL = 8000
    MAX_TB_LINES = 40
    try:
        data = resp.json()
        if isinstance(data, dict) and "traceback" in data and isinstance(data["traceback"], str):
            lines = data["traceback"].splitlines()
            if len(lines) > MAX_TB_LINES:
                data["traceback"] = "\n".join(lines[:MAX_TB_LINES]) + f"\n... truncated {len(lines) - MAX_TB_LINES} lines ..."
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        if len(pretty) > MAX_TOTAL:
            pretty = pretty[:MAX_TOTAL] + f"\n... truncated {len(pretty) - MAX_TOTAL} chars ..."
        return pretty
    except Exception:
        if len(text) > MAX_TOTAL:
            return text[:MAX_TOTAL] + f"\n... truncated {len(text) - MAX_TOTAL} chars ..."
        return text

def call_api(
    server, endpoint: str, method: str = "get", params=None, json_data=None, timeout: int = 10
) -> dict:
    method = method.lower()
    url = f"{get_server_api_url(server)}{endpoint}"
    logger.info(f"{method.upper()} {url} params={params} json_data={json_data}")

    def build_headers(cfg) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        body = ""
        if json_data is not None:
            body = json.dumps(json_data, separators=(",", ":"))
        if endpoint != "/health" and cfg.enable_hmac and cfg.hmac_secret:
            try:
                headers.update(create_hmac_headers(cfg.hmac_secret, body))
                if json_data is not None:
                    headers["Content-Type"] = "application/json"
                logger.debug(f"HMAC headers added for {url}")
            except Exception as e:
                logger.error(f"Failed to create HMAC headers: {e}")
        return headers

    cfg = security_config  # initial reference
    headers = build_headers(cfg)

    for attempt in (1, 2):
        try:
            resp = requests.request(
                method.upper(),
                url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=timeout,
            )
            logger.info(f"[{resp.status_code}] {url}")
            if resp.status_code == 401 and attempt == 1:
                # Reload security config and retry once (secret may have rotated)
                new_cfg = load_security_config()
                if new_cfg.hmac_secret != cfg.hmac_secret:
                    cfg = new_cfg
                    headers = build_headers(cfg)
                    logger.info("Retrying %s after HMAC secret reload", url)
                    continue
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as he:
            formatted = _format_error_body(resp)
            logger.error(
                "HTTPError status=%s url=%s error=%s\nResponse body:\n%s",
                getattr(resp, "status_code", None),
                url,
                he,
                formatted,
            )
            status_code = getattr(resp, 'status_code', None) if 'resp' in locals() else None
            return {
                "error": str(he),
                "status_code": status_code,
                "endpoint": endpoint,
            }
        except Exception as e:
            logger.exception(f"{type(e)} Exception for {url}: {e}")
            return {"error": str(e), "endpoint": endpoint}
    return {"error": "Unknown error", "endpoint": endpoint}
