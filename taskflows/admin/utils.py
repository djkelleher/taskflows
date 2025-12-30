"""Utility functions for admin module."""

import socket
from functools import cache
from typing import Optional

import requests

from taskflows.admin.models import ResponseData
from taskflows.common import logger

HOSTNAME = socket.gethostname()


def with_hostname(data: dict) -> ResponseData:
    """Add hostname to response data.

    Args:
        data: Dictionary data to add hostname to

    Returns:
        Dictionary with hostname added
    """
    return {**data, "hostname": HOSTNAME}


@cache
def get_public_ipv4() -> Optional[str]:
    """Detect and cache the machine's public IPv4 address.

    Returns:
        Public IPv4 address or None if detection fails
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
                logger.debug(f"Non-200 from {url}: {resp.status_code}")
                continue
            candidate = resp.text.strip().split()[0]
            logger.debug(f"Selected public IP {candidate} from {url}")
            return candidate
        except requests.RequestException as e:
            logger.debug(f"Request error from {url}: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error from {url}: {e}")

    logger.warning("Failed to determine public IPv4 address")
    return None
