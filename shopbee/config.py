"""ShopBee configuration — centralized constants for URLs, timeouts, and settings."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Bee Proxy ───────────────────────────────────────────────────────────

#: Base URL of the Bee proxy server.
BEES_PROXY_URL = "http://127.0.0.1:8787"

#: Bee API endpoints (relative to BEES_PROXY_URL).
BEE_CONVERSATIONS_PATH = "/v1/conversations"
BEE_TODOS_PATH = "/v1/todos"
BEE_FACTS_PATH = "/v1/facts"
BEE_ME_PATH = "/v1/me"


# ── Amazon URLs ─────────────────────────────────────────────────────────

#: Base URL for Amazon product search.
AMAZON_SEARCH_URL = "https://www.amazon.com/s?k={query}"

#: Template for a single Amazon product detail page (replace {asin}).
AMAZON_PRODUCT_DETAIL_TEMPLATE = "https://www.amazon.com/dp/{asin}"

#: Template for an Amazon wishlist link (replace {asin}).
AMAZON_WISHLIST_TEMPLATE = "https://www.amazon.com/hz/wishlist/ls/{asin}"


# ── Alexa Shopping Actions ──────────────────────────────────────────────

@dataclass(frozen=True)
class AlexaConfig:
    """Configuration for Alexa Shopping directive payloads.

    Attributes:
        namespace: The Alexa directive namespace (e.g., "Alexa.Shopping").
        payload_version: The version string of the directive payload schema.
        default_shopping_list_name: Default name used when creating a shopping list item.
    """
    namespace: str = "Alexa.Shopping"
    payload_version: str = "3"
    default_shopping_list_name: str = "Shopping List"


# ── Bee CLI Package ─────────────────────────────────────────────────────

#: The npm package name for the Bee CLI tool.
BEE_CLI_PACKAGE = "@beeai/cli"


# ── Timeout Defaults ────────────────────────────────────────────────────

CONVERSATIONS_TIMEOUT: int = 15
"""Default timeout (seconds) for subprocess calls to bee CLI."""

REQUEST_TIMEOUT: float = 5.0
"""Default timeout (seconds) for HTTP requests via the `requests` library."""

PRODUCT_LOOKUP_TIMEOUT: float = 10.0
"""Timeout (seconds) when fetching product details from Amazon."""


# ── Convenience Accessors ───────────────────────────────────────────────

def amazon_search_url(query: str) -> str:
    """Return a fully-formed Amazon search URL for *query*.

    Args:
        query: The search term to encode into the URL.

    Returns:
        A string like ``https://www.amazon.com/s?k=keyboard``.
    """
    return AMAZON_SEARCH_URL.format(query=query.replace(" ", "+"))


def amazon_product_url(asin: str) -> str:
    """Return a fully-formed Amazon product detail URL for *asin*.

    Args:
        asin: The 10-character ASIN string.

    Returns:
        A string like ``https://www.amazon.com/dp/B09ABCDEF``.
    """
    return AMAZON_PRODUCT_DETAIL_TEMPLATE.format(asin=asin)


def amazon_wishlist_url(asin: str) -> str:
    """Return a fully-formed Amazon wishlist URL for *asin*.

    Args:
        asin: The 10-character ASIN string.

    Returns:
        A string like ``https://www.amazon.com/hz/wishlist/ls/B09ABCDEF``.
    """
    return AMAZON_WISHLIST_TEMPLATE.format(asin=asin)


def bee_api_url(path: str) -> str:
    """Return a fully-formed Bee API URL for *path*.

    Args:
        path: A relative endpoint such as ``/v1/conversations``.

    Returns:
        A string like ``http://127.0.0.1:8787/v1/conversations``.
    """
    return f"{BEES_PROXY_URL}{path}"


# ── ASIN Inference ──────────────────────────────────────────────────────


def infer_asin(product_name: str) -> str:
    """Generate a deterministic ASIN-like identifier from a product name.

    Uses MD5 hashing to produce consistent results for the same input,
    ensuring that deduplication works reliably across calls.

    Args:
        product_name: The product name to convert into an ASIN-like string.

    Returns:
        A 10-character uppercase alphanumeric string resembling an Amazon ASIN.
    """
    import hashlib
    h = hashlib.md5(product_name.encode()).hexdigest()[:10].upper()
    # Ensure first character is always a letter (Amazon ASINs start with A-Z)
    first = h[0]
    if first.isdigit():
        first = chr(ord('A') + int(first))  # '0' -> 'A', '1' -> 'B', etc.
    result = f"{first}{h[1:9]}{h[9]}"
    logger.debug("infer_asin(%r) -> %s", product_name, result)
    return result


def setup_logging(level: int | None = None) -> logging.Logger:
    """Configure ShopBee's root logger.

    Call this early in your application to enable structured logging output.
    If no level is provided, defaults to INFO when running as a script, DEBUG otherwise.

    Args:
        level: Logging level (e.g., logging.DEBUG, logging.INFO). Defaults to None.

    Returns:
        The configured logger instance.
    """
    if level is None:
        import sys
        level = logging.DEBUG if len(sys.argv) > 1 and "-v" in sys.argv else logging.INFO

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)

    shopbee_logger = logging.getLogger("shopbee")
    shopbee_logger.setLevel(level)
    if not shopbee_logger.handlers:
        shopbee_logger.addHandler(handler)

    logger.debug("Logging configured at level %s", logging.getLevelName(level))
    return shopbee_logger


# ── Shared Instance ─────────────────────────────────────────────────────

#: Singleton Alexa configuration used across the codebase.
ALEXA = AlexaConfig()
